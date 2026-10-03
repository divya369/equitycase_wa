package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"os"
	"path/filepath"
	"strings"
)

// Meta's cap for a video sent through the Cloud API.
const maxUploadBytes = 16 << 20

// MediaUpload is what the upload returned: the id goes into
// MARKETING_HEADER_VIDEO_ID, the URL is the endpoint it was sent to.
type MediaUpload struct {
	ID       string
	URL      string
	MimeType string
	Bytes    int64
}

// UploadMedia sends a local file to the business number's media store. The id
// it returns is what a template's media header needs; it expires after about
// 30 days, so upload shortly before a blast.
func (c *Client) UploadMedia(ctx context.Context, path string) (*MediaUpload, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if info.Size() > maxUploadBytes {
		return nil, fmt.Errorf("%s is %.1f MB, over Meta's 16 MB limit",
			filepath.Base(path), float64(info.Size())/(1<<20))
	}

	mimeType, err := mimeFor(path)
	if err != nil {
		return nil, err
	}

	// 16 MB at most: buffer it, one plain multipart request, no chunking
	var body bytes.Buffer
	form := multipart.NewWriter(&body)
	if err := form.WriteField("messaging_product", "whatsapp"); err != nil {
		return nil, err
	}
	if err := form.WriteField("type", mimeType); err != nil {
		return nil, err
	}
	// CreateFormFile would label the part application/octet-stream, which
	// Meta rejects — set the real type on the part itself.
	header := make(textproto.MIMEHeader)
	header.Set("Content-Disposition", fmt.Sprintf(
		`form-data; name="file"; filename=%q`, filepath.Base(path)))
	header.Set("Content-Type", mimeType)
	part, err := form.CreatePart(header)
	if err != nil {
		return nil, err
	}
	if _, err := io.Copy(part, file); err != nil {
		return nil, err
	}
	if err := form.Close(); err != nil {
		return nil, err
	}

	url := fmt.Sprintf("%s/%s/%s/media",
		strings.TrimRight(c.cfg.GraphBaseURL, "/"), c.cfg.APIVersion, c.cfg.PhoneNumberID)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, &body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", form.FormDataContentType())
	req.Header.Set("Authorization", "Bearer "+c.cfg.AccessToken)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	payload, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseRead))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, parseAPIError(resp.StatusCode, payload)
	}

	var ok struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(payload, &ok); err != nil {
		return nil, err
	}
	if ok.ID == "" {
		return nil, errors.New("upload accepted but no media id came back")
	}

	return &MediaUpload{
		ID:       ok.ID,
		URL:      url,
		MimeType: mimeType,
		Bytes:    info.Size(),
	}, nil
}

func mimeFor(path string) (string, error) {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".mp4":
		return "video/mp4", nil
	case ".3gp", ".3gpp":
		return "video/3gpp", nil
	case ".webp":
		return "image/webp", nil
	case ".jpg", ".jpeg":
		return "image/jpeg", nil
	case ".png":
		return "image/png", nil
	case ".pdf":
		return "application/pdf", nil
	default:
		return "", fmt.Errorf("unsupported file type %q — use .mp4", filepath.Ext(path))
	}
}
