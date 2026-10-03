package main

import (
	"context"
	"sync"
	"sync/atomic"
	"time"
)

// Result is one recipient's outcome. Err == nil means Meta accepted it;
// delivery itself is reported later by the webhook, not here.
type Result struct {
	Recipient Recipient
	WAMID     string
	Attempts  int
	Err       error
	Elapsed   time.Duration
}

// Sender fans the recipients out over a fixed pool of goroutines, with a
// shared token-bucket limiter so the Cloud API's per-second cap is respected
// no matter how many workers there are.
type Sender struct {
	client  *Client
	workers int
	limiter *limiter
	dryRun  bool

	Sent   atomic.Int64
	Failed atomic.Int64
}

func NewSender(client *Client, workers int, ratePerSecond float64, dryRun bool) *Sender {
	if workers < 1 {
		workers = 1
	}
	return &Sender{
		client:  client,
		workers: workers,
		limiter: newLimiter(ratePerSecond),
		dryRun:  dryRun,
	}
}

// Run sends to everyone and returns the results in completion order. It stops
// handing out work as soon as ctx is cancelled (Ctrl+C); sends already in
// flight are allowed to finish.
func (s *Sender) Run(ctx context.Context, recipients []Recipient, onResult func(Result)) []Result {
	jobs := make(chan Recipient)
	results := make(chan Result, s.workers)

	var workers sync.WaitGroup
	for range s.workers {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for recipient := range jobs {
				results <- s.sendOne(ctx, recipient)
			}
		}()
	}

	go func() {
		defer close(jobs)
		for _, recipient := range recipients {
			select {
			case <-ctx.Done():
				return
			case jobs <- recipient:
			}
		}
	}()

	go func() {
		workers.Wait()
		close(results)
	}()

	out := make([]Result, 0, len(recipients))
	for result := range results {
		if result.Err == nil {
			s.Sent.Add(1)
		} else {
			s.Failed.Add(1)
		}
		if onResult != nil {
			onResult(result)
		}
		out = append(out, result)
	}
	return out
}

func (s *Sender) sendOne(ctx context.Context, recipient Recipient) Result {
	started := time.Now()

	if err := s.limiter.wait(ctx); err != nil {
		return Result{Recipient: recipient, Err: err, Elapsed: time.Since(started)}
	}

	if s.dryRun {
		return Result{
			Recipient: recipient,
			WAMID:     "dry-run",
			Attempts:  0,
			Elapsed:   time.Since(started),
		}
	}

	wamid, attempts, err := s.client.SendTemplate(ctx, recipient.WaID)
	return Result{
		Recipient: recipient,
		WAMID:     wamid,
		Attempts:  attempts,
		Err:       err,
		Elapsed:   time.Since(started),
	}
}

// limiter is a token bucket shared by every worker: one token per send,
// refilled at `rate` per second, with a small burst so short stalls recover.
type limiter struct {
	tokens chan struct{}
	stop   chan struct{}
	once   sync.Once
}

func newLimiter(ratePerSecond float64) *limiter {
	if ratePerSecond <= 0 {
		return &limiter{} // unlimited
	}

	// a small burst smooths short stalls without flooding Meta (and risking 429)
	burst := int(ratePerSecond / 5)
	if burst < 1 {
		burst = 1
	}
	l := &limiter{
		tokens: make(chan struct{}, burst),
		stop:   make(chan struct{}),
	}
	for range burst {
		l.tokens <- struct{}{}
	}

	interval := time.Duration(float64(time.Second) / ratePerSecond)
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-l.stop:
				return
			case <-ticker.C:
				select {
				case l.tokens <- struct{}{}:
				default: // bucket full
				}
			}
		}
	}()
	return l
}

func (l *limiter) wait(ctx context.Context) error {
	if l.tokens == nil {
		return ctx.Err()
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-l.tokens:
		return nil
	}
}

func (l *limiter) close() {
	if l.tokens == nil {
		return
	}
	l.once.Do(func() { close(l.stop) })
}
