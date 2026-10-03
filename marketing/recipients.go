package main

import (
	"errors"
	"fmt"
	"strings"
)

// Recipient is one row of work: a wa_id (digits only, no '+') and where it
// came from, so a failure can be traced back to the CSV line.
type Recipient struct {
	WaID   string
	Source string
}

var errBadPhone = errors.New("not a phone number")

func digitsOnly(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// normalizePhone turns "+91 98200-11223" into "919820011223". A number
// without a country code gets DEFAULT_COUNTRY_CODE, when that is set.
func normalizePhone(raw string, defaultCountryCode string) (string, error) {
	digits := digitsOnly(raw)
	if digits == "" {
		return "", errBadPhone
	}
	// local form (India: 10 digits) -> prefix the country code. Without one
	// we refuse: a wa_id always carries the country code, and guessing it
	// would message a stranger.
	if len(digits) <= 10 {
		if defaultCountryCode == "" {
			return "", fmt.Errorf(
				"%w: %q has no country code (set %s)", errBadPhone, raw, envDefaultCC)
		}
		digits = defaultCountryCode + digits
	}
	if len(digits) < 8 || len(digits) > 15 {
		return "", fmt.Errorf("%w: %d digits", errBadPhone, len(digits))
	}
	return digits, nil
}

// recipientsFromArgs builds the list from command-line numbers.
func recipientsFromArgs(args []string, defaultCountryCode string) ([]Recipient, error) {
	out := make([]Recipient, 0, len(args))
	for i, arg := range args {
		waID, err := normalizePhone(arg, defaultCountryCode)
		if err != nil {
			return nil, fmt.Errorf("argument %d (%q): %w", i+1, arg, err)
		}
		out = append(out, Recipient{WaID: waID, Source: fmt.Sprintf("arg:%d", i+1)})
	}
	return out, nil
}

// dedupe keeps the first occurrence of each wa_id: never message the same
// person twice in one run.
func dedupe(in []Recipient) (out []Recipient, duplicates int) {
	seen := make(map[string]struct{}, len(in))
	out = make([]Recipient, 0, len(in))
	for _, r := range in {
		if _, ok := seen[r.WaID]; ok {
			duplicates++
			continue
		}
		seen[r.WaID] = struct{}{}
		out = append(out, r)
	}
	return out, duplicates
}

// readCSV loads recipients from a CSV file.
//
// TODO: fill in once the column format is decided. Return one Recipient per
// row, with Source = "<path>:<line>" so failures point at the row.
func readCSV(path string, defaultCountryCode string) ([]Recipient, error) {
	return nil, fmt.Errorf("readCSV: not implemented yet (%s)", path)
}
