package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func testConfig(serverURL string) *Config {
	return &Config{
		AccessToken:   "test-token",
		PhoneNumberID: "100000000000001",
		APIVersion:    "v23.0",
		GraphBaseURL:  serverURL,
		TemplateName:  "eq_amc_marketing",
		TemplateLang:  "en",
	}
}

func okHandler(calls *atomic.Int64, bodies chan<- map[string]any) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		var body map[string]any
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		if bodies != nil {
			bodies <- body
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"messages":[{"id":"wamid.TEST"}]}`))
	}
}

func TestSendTemplatePayloadAndAuth(t *testing.T) {
	var calls atomic.Int64
	bodies := make(chan map[string]any, 1)

	var gotAuth, gotPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		gotPath = r.URL.Path
		okHandler(&calls, bodies)(w, r)
	}))
	defer server.Close()

	client := NewClient(testConfig(server.URL), 5*time.Second)
	wamid, attempts, err := client.SendTemplate(context.Background(), "919820011223")
	if err != nil {
		t.Fatalf("send: %v", err)
	}
	if wamid != "wamid.TEST" || attempts != 1 {
		t.Fatalf("wamid=%q attempts=%d", wamid, attempts)
	}
	if gotAuth != "Bearer test-token" {
		t.Errorf("auth header = %q", gotAuth)
	}
	if want := "/v23.0/100000000000001/messages"; gotPath != want {
		t.Errorf("path = %q, want %q", gotPath, want)
	}

	body := <-bodies
	if body["messaging_product"] != "whatsapp" || body["to"] != "919820011223" {
		t.Errorf("payload = %#v", body)
	}
	template := body["template"].(map[string]any)
	if template["name"] != "eq_amc_marketing" {
		t.Errorf("template = %#v", template)
	}
	if _, has := template["components"]; has {
		t.Error("no components expected without a media header")
	}
}

func TestVideoHeaderIsSentWhenConfigured(t *testing.T) {
	var calls atomic.Int64
	bodies := make(chan map[string]any, 1)
	server := httptest.NewServer(okHandler(&calls, bodies))
	defer server.Close()

	cfg := testConfig(server.URL)
	cfg.HeaderVideoID = "media-123"
	client := NewClient(cfg, 5*time.Second)

	if _, _, err := client.SendTemplate(context.Background(), "919820011223"); err != nil {
		t.Fatalf("send: %v", err)
	}

	body := <-bodies
	components := body["template"].(map[string]any)["components"].([]any)
	header := components[0].(map[string]any)
	param := header["parameters"].([]any)[0].(map[string]any)
	video := param["video"].(map[string]any)
	if header["type"] != "header" || video["id"] != "media-123" {
		t.Errorf("components = %#v", components)
	}
}

func TestRetriesServerErrorsThenSucceeds(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) < 3 {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(`{"error":{"message":"try later","code":1}}`))
			return
		}
		_, _ = w.Write([]byte(`{"messages":[{"id":"wamid.AFTER_RETRY"}]}`))
	}))
	defer server.Close()

	client := NewClient(testConfig(server.URL), 5*time.Second)
	wamid, attempts, err := client.SendTemplate(context.Background(), "919820011223")
	if err != nil {
		t.Fatalf("send: %v", err)
	}
	if wamid != "wamid.AFTER_RETRY" || attempts != 3 {
		t.Fatalf("wamid=%q attempts=%d", wamid, attempts)
	}
}

func TestDoesNotRetryPermanentError(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":{"message":"invalid recipient","code":131026}}`))
	}))
	defer server.Close()

	client := NewClient(testConfig(server.URL), 5*time.Second)
	_, attempts, err := client.SendTemplate(context.Background(), "919820011223")
	if err == nil {
		t.Fatal("expected an error")
	}
	if attempts != 1 || calls.Load() != 1 {
		t.Fatalf("attempts=%d calls=%d — a 4xx must not be retried", attempts, calls.Load())
	}
}

func TestSenderSendsEveryRecipientConcurrently(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(okHandler(&calls, nil))
	defer server.Close()

	recipients := make([]Recipient, 50)
	for i := range recipients {
		recipients[i] = Recipient{WaID: "9198200000" + pad(i), Source: "test"}
	}

	sender := NewSender(NewClient(testConfig(server.URL), 5*time.Second), 10, 0, false)
	defer sender.limiter.close()

	results := sender.Run(context.Background(), recipients, nil)
	if len(results) != len(recipients) {
		t.Fatalf("results=%d, want %d", len(results), len(recipients))
	}
	if sender.Sent.Load() != 50 || sender.Failed.Load() != 0 {
		t.Fatalf("sent=%d failed=%d", sender.Sent.Load(), sender.Failed.Load())
	}
	if calls.Load() != 50 {
		t.Fatalf("server calls=%d", calls.Load())
	}
}

func TestRateLimitIsRespected(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(okHandler(&calls, nil))
	defer server.Close()

	recipients := make([]Recipient, 8)
	for i := range recipients {
		recipients[i] = Recipient{WaID: "9198200000" + pad(i), Source: "test"}
	}

	// burst of 4, then 4 more at 20/s -> at least ~200ms
	sender := NewSender(NewClient(testConfig(server.URL), 5*time.Second), 8, 20, false)
	defer sender.limiter.close()

	started := time.Now()
	sender.Run(context.Background(), recipients, nil)
	if elapsed := time.Since(started); elapsed < 150*time.Millisecond {
		t.Fatalf("8 sends at 20/s took only %s — the limiter is not working", elapsed)
	}
}

func TestCancelledContextStopsTheRun(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(okHandler(&calls, nil))
	defer server.Close()

	recipients := make([]Recipient, 100)
	for i := range recipients {
		recipients[i] = Recipient{WaID: "9198200000" + pad(i), Source: "test"}
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	sender := NewSender(NewClient(testConfig(server.URL), 5*time.Second), 4, 0, false)
	defer sender.limiter.close()

	results := sender.Run(ctx, recipients, nil)
	if len(results) == len(recipients) {
		t.Fatal("a cancelled run must not send to everyone")
	}
}

func TestDryRunSendsNothing(t *testing.T) {
	var calls atomic.Int64
	server := httptest.NewServer(okHandler(&calls, nil))
	defer server.Close()

	sender := NewSender(NewClient(testConfig(server.URL), 5*time.Second), 2, 0, true)
	defer sender.limiter.close()

	results := sender.Run(context.Background(), []Recipient{{WaID: "919820011223"}}, nil)
	if calls.Load() != 0 {
		t.Fatalf("dry run called the API %d time(s)", calls.Load())
	}
	if len(results) != 1 || results[0].WAMID != "dry-run" {
		t.Fatalf("results = %#v", results)
	}
}

func TestNormalizePhone(t *testing.T) {
	cases := []struct {
		raw, cc, want string
		wantErr       bool
	}{
		{raw: "+91 98200-11223", cc: "91", want: "919820011223"},
		{raw: "9820011223", cc: "91", want: "919820011223"},
		{raw: "919820011223", cc: "91", want: "919820011223"},
		{raw: "(982) 001-1223", cc: "", wantErr: true}, // 10 digits, no country code
		{raw: "abc", cc: "91", wantErr: true},
		{raw: "", cc: "91", wantErr: true},
	}
	for _, c := range cases {
		got, err := normalizePhone(c.raw, c.cc)
		if c.wantErr {
			if err == nil {
				t.Errorf("normalizePhone(%q) = %q, want an error", c.raw, got)
			}
			continue
		}
		if err != nil || got != c.want {
			t.Errorf("normalizePhone(%q) = %q, %v; want %q", c.raw, got, err, c.want)
		}
	}
}

func TestDedupeKeepsFirst(t *testing.T) {
	in := []Recipient{
		{WaID: "919820011223", Source: "arg:1"},
		{WaID: "919820011224", Source: "arg:2"},
		{WaID: "919820011223", Source: "arg:3"},
	}
	out, duplicates := dedupe(in)
	if duplicates != 1 || len(out) != 2 || out[0].Source != "arg:1" {
		t.Fatalf("out=%#v duplicates=%d", out, duplicates)
	}
}

func TestMaskHidesMostDigits(t *testing.T) {
	if got := mask("919820011223"); got != "919820****23" {
		t.Fatalf("mask = %q", got)
	}
}

func pad(i int) string {
	return string(rune('0'+i/10)) + string(rune('0'+i%10))
}
