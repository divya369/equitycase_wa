package main

import (
	"errors"
	"fmt"
	"os"
	"strings"
)

// Env keys. The token is a secret: it is never printed, only its presence is.
const (
	envAccessToken    = "META_ACCESS_TOKEN"
	envPhoneNumberID  = "BUSINESS_PHONE_NUMBER_ID"
	envAPIVersion     = "META_API_VERSION"
	envGraphBaseURL   = "META_GRAPH_BASE_URL"
	envTemplateName   = "MARKETING_TEMPLATE_NAME"
	envTemplateLang   = "MARKETING_TEMPLATE_LANG"
	envHeaderVideoID  = "MARKETING_HEADER_VIDEO_ID"
	envHeaderVideoURL = "MARKETING_HEADER_VIDEO_URL"
	envDefaultCC      = "DEFAULT_COUNTRY_CODE"
)

// Config is everything the sender needs, read once at startup.
type Config struct {
	AccessToken   string
	PhoneNumberID string
	APIVersion    string
	GraphBaseURL  string
	TemplateName  string
	TemplateLang  string

	// Optional: only for a template whose header is a video. Give the
	// uploaded media id (preferred) or a public link.
	HeaderVideoID  string
	HeaderVideoURL string

	// Optional: prefix for numbers written without a country code (e.g. "91")
	DefaultCountryCode string
}

// LoadConfig reads the environment and refuses to start on anything missing.
func LoadConfig() (*Config, error) {
	cfg := &Config{
		AccessToken:        strings.TrimSpace(os.Getenv(envAccessToken)),
		PhoneNumberID:      strings.TrimSpace(os.Getenv(envPhoneNumberID)),
		APIVersion:         strings.TrimSpace(os.Getenv(envAPIVersion)),
		GraphBaseURL:       strings.TrimSpace(os.Getenv(envGraphBaseURL)),
		TemplateName:       strings.TrimSpace(os.Getenv(envTemplateName)),
		TemplateLang:       strings.TrimSpace(os.Getenv(envTemplateLang)),
		HeaderVideoID:      strings.TrimSpace(os.Getenv(envHeaderVideoID)),
		HeaderVideoURL:     strings.TrimSpace(os.Getenv(envHeaderVideoURL)),
		DefaultCountryCode: digitsOnly(os.Getenv(envDefaultCC)),
	}

	if cfg.APIVersion == "" {
		cfg.APIVersion = "v23.0"
	}
	if cfg.GraphBaseURL == "" {
		cfg.GraphBaseURL = "https://graph.facebook.com"
	}
	if cfg.TemplateLang == "" {
		cfg.TemplateLang = "en"
	}

	var missing []string
	for key, value := range map[string]string{
		envAccessToken:   cfg.AccessToken,
		envPhoneNumberID: cfg.PhoneNumberID,
		envTemplateName:  cfg.TemplateName,
	} {
		if value == "" {
			missing = append(missing, key)
		}
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required env: %s", strings.Join(missing, ", "))
	}
	if cfg.HeaderVideoID != "" && cfg.HeaderVideoURL != "" {
		return nil, errors.New("set only one of " + envHeaderVideoID + " / " + envHeaderVideoURL)
	}

	return cfg, nil
}

// SendURL is the Cloud API endpoint for this business number.
func (c *Config) SendURL() string {
	return fmt.Sprintf("%s/%s/%s/messages",
		strings.TrimRight(c.GraphBaseURL, "/"), c.APIVersion, c.PhoneNumberID)
}
