// Command marketing sends ONE approved WhatsApp marketing template to one
// number or to a list, concurrently. Run it by hand — nothing here is wired
// into the backend.
//
//	go run . +919820011223
//	go run . --csv=customers.csv --workers=16 --rate=20
//	go run . --dry-run --csv=customers.csv          # read + validate only
//
// Config comes from the env file (--env-file, default ../.env):
//
//	META_ACCESS_TOKEN          permanent system-user token
//	BUSINESS_PHONE_NUMBER_ID   the sending number's id
//	MARKETING_TEMPLATE_NAME    e.g. eq_amc_marketing
//	MARKETING_TEMPLATE_LANG    default "en"
//	META_API_VERSION           default "v23.0"
//	MARKETING_HEADER_VIDEO_ID  only when the template header is a video
//	DEFAULT_COUNTRY_CODE       e.g. 91, for numbers written without one
//
// Exit code is 1 when any recipient failed, so a script can act on it.
package main

import (
	"context"
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/joho/godotenv"
)

func main() {
	os.Exit(run())
}

func run() int {
	var (
		envFile = flag.String("env-file", "../.env", "path to the environment file")
		csvPath = flag.String("csv", "", "CSV of recipients (instead of number arguments)")
		workers = flag.Int("workers", 8, "parallel senders")
		rate    = flag.Float64("rate", 15, "messages per second (0 = no limit)")
		timeout = flag.Duration("timeout", 15*time.Second, "per-request timeout")
		outPath = flag.String("out", "", "write a per-recipient result CSV here")
		dryRun  = flag.Bool("dry-run", false, "resolve recipients, send nothing")
		upload  = flag.String("upload", "", "upload this file to Meta, print its media id, exit")
	)
	flag.Usage = usage
	flag.Parse()

	log.SetFlags(log.Ltime)

	if err := godotenv.Load(*envFile); err != nil {
		log.Printf("could not read %s: %v", *envFile, err)
		log.Printf("(carrying on with the process environment)")
	}

	cfg, err := LoadConfig()
	if err != nil {
		log.Printf("config: %v", err)
		return 2
	}

	if *upload != "" {
		return uploadMedia(cfg, *upload, *timeout)
	}

	recipients, err := collectRecipients(flag.Args(), *csvPath, cfg.DefaultCountryCode)
	if err != nil {
		log.Printf("recipients: %v", err)
		return 2
	}
	recipients, duplicates := dedupe(recipients)
	if len(recipients) == 0 {
		log.Print("no recipients")
		usage()
		return 2
	}

	log.Printf("template=%s lang=%s recipients=%d duplicates_skipped=%d workers=%d rate=%.1f/s dry_run=%t",
		cfg.TemplateName, cfg.TemplateLang, len(recipients), duplicates, *workers, *rate, *dryRun)

	// Ctrl+C: stop handing out new work, let in-flight sends finish
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	sender := NewSender(NewClient(cfg, *timeout), *workers, *rate, *dryRun)
	defer sender.limiter.close()

	started := time.Now()
	var progress sync.Mutex
	done := 0

	results := sender.Run(ctx, recipients, func(r Result) {
		progress.Lock()
		defer progress.Unlock()
		done++
		if r.Err != nil {
			log.Printf("[%d/%d] %s FAILED after %d attempt(s): %v",
				done, len(recipients), mask(r.Recipient.WaID), r.Attempts, r.Err)
			return
		}
		if done%25 == 0 || done == len(recipients) {
			log.Printf("[%d/%d] sent", done, len(recipients))
		}
	})

	elapsed := time.Since(started)
	sent, failed := sender.Sent.Load(), sender.Failed.Load()
	skipped := len(recipients) - len(results)

	log.Printf("done in %s — sent=%d failed=%d not_attempted=%d (%.1f msg/s)",
		elapsed.Round(time.Millisecond), sent, failed, skipped,
		float64(sent)/max(elapsed.Seconds(), 0.001))

	if *outPath != "" {
		if err := writeResults(*outPath, results); err != nil {
			log.Printf("could not write %s: %v", *outPath, err)
			return 1
		}
		log.Printf("results written to %s", *outPath)
	}

	if failed > 0 || skipped > 0 {
		return 1
	}
	return 0
}

func usage() {
	fmt.Fprint(os.Stderr, `Send the approved WhatsApp marketing template.

  marketing [flags] <phone> [phone...]
  marketing [flags] --csv=path.csv

Flags:
`)
	flag.PrintDefaults()
}

// uploadMedia puts a local video (or image/pdf) in Meta's media store and
// prints the id for MARKETING_HEADER_VIDEO_ID. Media ids expire in ~30 days.
func uploadMedia(cfg *Config, path string, timeout time.Duration) int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// a video upload needs longer than a message send
	client := NewClient(cfg, max(timeout, 5*time.Minute))

	log.Printf("uploading %s ...", path)
	media, err := client.UploadMedia(ctx, path)
	if err != nil {
		log.Printf("upload failed: %v", err)
		return 1
	}

	fmt.Printf("\nendpoint : %s\n", media.URL)
	fmt.Printf("type     : %s (%.1f MB)\n", media.MimeType, float64(media.Bytes)/(1<<20))
	fmt.Printf("media id : %s\n\n", media.ID)
	fmt.Printf("Put this in your .env (ids expire in about 30 days):\n")
	fmt.Printf("MARKETING_HEADER_VIDEO_ID=%s\n", media.ID)
	return 0
}

func collectRecipients(args []string, csvPath, defaultCC string) ([]Recipient, error) {
	switch {
	case csvPath != "" && len(args) > 0:
		return nil, errors.New("give either --csv or phone numbers, not both")
	case csvPath != "":
		return readCSV(csvPath, defaultCC)
	default:
		return recipientsFromArgs(args, defaultCC)
	}
}

// mask keeps logs useful without printing whole phone numbers.
func mask(waID string) string {
	if len(waID) <= 6 {
		return "***"
	}
	return waID[:len(waID)-6] + "****" + waID[len(waID)-2:]
}

func writeResults(path string, results []Result) error {
	sort.Slice(results, func(i, j int) bool {
		return results[i].Recipient.Source < results[j].Recipient.Source
	})

	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	w := csv.NewWriter(file)
	defer w.Flush()

	header := []string{"wa_id", "source", "status", "wamid", "attempts", "error"}
	if err := w.Write(header); err != nil {
		return err
	}
	for _, r := range results {
		status, failure := "sent", ""
		if r.Err != nil {
			status, failure = "failed", r.Err.Error()
		}
		row := []string{
			r.Recipient.WaID,
			r.Recipient.Source,
			status,
			r.WAMID,
			strconv.Itoa(r.Attempts),
			failure,
		}
		if err := w.Write(row); err != nil {
			return err
		}
	}
	return w.Error()
}
