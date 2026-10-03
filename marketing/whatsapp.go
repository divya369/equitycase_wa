package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"time"
)

const (
	maxAttempts     = 3
	backoffBase     = 500 * time.Millisecond
	maxResponseRead = 1 << 16 // plenty for a Graph API reply
)

// APIError is what the Graph API said went wrong. Only 429 and 5xx are worth
// retrying; a 4xx means this recipient will fail again the same way.
type APIError struct {
	HTTPStatus int
	Code       int
	Subcode    int
	Message    string
	Retryable  bool
}

func (e *APIError) Error() string {
	return fmt.Sprintf("http %d: meta code %d/%d: %s",
		e.HTTPStatus, e.Code, e.Subcode, e.Message)
}

// Client sends template messages through the WhatsApp Cloud API.
// One Client is shared by every worker: http.Client is safe for that and
// keeps the connections pooled.
type Client struct {
	cfg  *Config
	http *http.Client
}

func NewClient(cfg *Config, timeout time.Duration) *Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	// one host, many parallel sends
	transport.MaxIdleConns = 200
	transport.MaxIdleConnsPerHost = 200
	transport.MaxConnsPerHost = 0

	return &Client{
		cfg:  cfg,
		http: &http.Client{Timeout: timeout, Transport: transport},
	}
}

// templatePayload is the Cloud API body for a template send.
func (c *Client) templatePayload(waID string) map[string]any {
	template := map[string]any{
		"name":     c.cfg.TemplateName,
		"language": map[string]string{"code": c.cfg.TemplateLang},
	}

	// A video header needs its parameter; a template without one must not
	// carry components at all.
	if media := c.headerMedia(); media != nil {
		template["components"] = []any{
			map[string]any{
				"type": "header",
				"parameters": []any{
					map[string]any{"type": "video", "video": media},
				},
			},
		}
	}

	return map[string]any{
		"messaging_product": "whatsapp",
		"recipient_type":    "individual",
		"to":                waID,
		"type":              "template",
		"template":          template,
	}
}

func (c *Client) headerMedia() map[string]string {
	switch {
	case c.cfg.HeaderVideoID != "":
		return map[string]string{"id": c.cfg.HeaderVideoID}
	case c.cfg.HeaderVideoURL != "":
		return map[string]string{"link": c.cfg.HeaderVideoURL}
	default:
		return nil
	}
}

// SendTemplate delivers the marketing template to one number and returns the
// wamid. It retries 429/5xx and network errors with exponential backoff and
// jitter, and stops as soon as ctx is cancelled.
func (c *Client) SendTemplate(ctx context.Context, waID string) (wamid string, attempts int, err error) {
	body, err := json.Marshal(c.templatePayload(waID))
	if err != nil {
		return "", 0, fmt.Errorf("encode payload: %w", err)
	}

	for attempt := 1; attempt <= maxAttempts; attempt++ {
		wamid, err = c.send(ctx, body)
		if err == nil {
			return wamid, attempt, nil
		}
		if ctx.Err() != nil {
			return "", attempt, ctx.Err()
		}

		var apiErr *APIError
		if errors.As(err, &apiErr) && !apiErr.Retryable {
			return "", attempt, err
		}
		if attempt == maxAttempts {
			return "", attempt, err
		}

		// 0.5s, 1s, 2s ... plus jitter, so retries don't line up
		wait := backoffBase * time.Duration(1<<(attempt-1))
		wait += time.Duration(rand.Int63n(int64(wait / 2)))
		select {
		case <-ctx.Done():
			return "", attempt, ctx.Err()
		case <-time.After(wait):
		}
	}

	return "", maxAttempts, err
}

func (c *Client) send(ctx context.Context, body []byte) (string, error) {
	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost, c.cfg.SendURL(), bytes.NewReader(body),
	)
	if err != nil {
		return "", fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.cfg.AccessToken)

	resp, err := c.http.Do(req)
	if err != nil {
		// timeouts and connection failures are worth another try
		return "", fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	payload, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseRead))
	if err != nil {
		return "", fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", parseAPIError(resp.StatusCode, payload)
	}

	var ok struct {
		Messages []struct {
			ID string `json:"id"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(payload, &ok); err != nil {
		return "", fmt.Errorf("decode response: %w", err)
	}
	if len(ok.Messages) == 0 || ok.Messages[0].ID == "" {
		return "", errors.New("accepted but no wamid in the response")
	}
	return ok.Messages[0].ID, nil
}

func parseAPIError(status int, payload []byte) error {
	var wrapper struct {
		Error struct {
			Message   string `json:"message"`
			Code      int    `json:"code"`
			Subcode   int    `json:"error_subcode"`
			ErrorData struct {
				Details string `json:"details"`
			} `json:"error_data"`
		} `json:"error"`
	}
	_ = json.Unmarshal(payload, &wrapper)

	message := wrapper.Error.Message
	if detail := wrapper.Error.ErrorData.Details; detail != "" {
		message = message + " — " + detail
	}
	if message == "" {
		message = string(payload)
	}

	return &APIError{
		HTTPStatus: status,
		Code:       wrapper.Error.Code,
		Subcode:    wrapper.Error.Subcode,
		Message:    message,
		// 368/131048 are rate/quality throttles; 4xx otherwise is permanent
		Retryable: status == http.StatusTooManyRequests || status >= 500 ||
			wrapper.Error.Code == 131048 || wrapper.Error.Code == 368,
	}
}
