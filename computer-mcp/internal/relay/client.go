package relay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

const maxResponseBytes = 8 << 20

type APIError struct {
	Status  int
	Code    string
	Message string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("relay API %s (%d): %s", e.Code, e.Status, e.Message)
}

type Action struct {
	Type       string   `json:"type"`
	X          int      `json:"x,omitempty"`
	Y          int      `json:"y,omitempty"`
	ToX        int      `json:"toX,omitempty"`
	ToY        int      `json:"toY,omitempty"`
	Button     string   `json:"button,omitempty"`
	State      string   `json:"state,omitempty"`
	Count      int      `json:"count,omitempty"`
	Text       string   `json:"text,omitempty"`
	Keys       []string `json:"keys,omitempty"`
	Key        string   `json:"key,omitempty"`
	DurationMS int      `json:"durationMs,omitempty"`
	Delta      int      `json:"delta,omitempty"`
	Direction  string   `json:"direction,omitempty"`
}

type CursorPosition struct {
	X      int `json:"x"`
	Y      int `json:"y"`
	Screen int `json:"screen"`
	Window int `json:"window"`
}

type Client struct {
	baseURL string
	token   string
	http    *http.Client
}

func NewClient(baseURL, token string, client *http.Client) (*Client, error) {
	parsed, err := url.Parse(strings.TrimRight(baseURL, "/"))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" || parsed.RawQuery != "" || parsed.User != nil {
		return nil, fmt.Errorf("invalid Relay base URL")
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, fmt.Errorf("Relay base URL must use http or https")
	}
	if len(token) < 12 {
		return nil, fmt.Errorf("Relay operator token must contain at least 12 characters")
	}
	if client == nil {
		client = http.DefaultClient
	}
	return &Client{baseURL: parsed.String(), token: token, http: client}, nil
}

func (c *Client) Claim(ctx context.Context, agentID string) error {
	return c.doJSON(ctx, http.MethodPost, "/api/v1/control/agent/claim", map[string]any{"agentId": agentID}, nil)
}

func (c *Client) Release(ctx context.Context, agentID string) error {
	return c.doJSON(ctx, http.MethodPost, "/api/v1/control/agent/release", map[string]any{"agentId": agentID}, nil)
}

func (c *Client) Apply(ctx context.Context, agentID string, actions []Action) error {
	if err := c.Claim(ctx, agentID); err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodPost, "/api/v1/input", map[string]any{
		"agentId": agentID,
		"actions": actions,
	}, nil)
}

func (c *Client) Screenshot(ctx context.Context) ([]byte, error) {
	response, err := c.request(ctx, http.MethodGet, "/api/v1/screenshot", nil)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if err := responseError(response); err != nil {
		return nil, err
	}
	image, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read screenshot: %w", err)
	}
	if len(image) > maxResponseBytes {
		return nil, fmt.Errorf("screenshot exceeds 8 MiB")
	}
	if len(image) < 8 || string(image[:8]) != "\x89PNG\r\n\x1a\n" {
		return nil, fmt.Errorf("desktop returned an invalid PNG screenshot")
	}
	return image, nil
}

func (c *Client) Accessibility(ctx context.Context) ([]byte, error) {
	response, err := c.request(ctx, http.MethodGet, "/api/v1/accessibility", nil)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if err := responseError(response); err != nil {
		return nil, err
	}
	return readLimited(response.Body, maxResponseBytes)
}

func (c *Client) Cursor(ctx context.Context) (CursorPosition, error) {
	var position CursorPosition
	err := c.doJSON(ctx, http.MethodGet, "/api/v1/cursor", nil, &position)
	return position, err
}

func (c *Client) doJSON(ctx context.Context, method, path string, body, destination any) error {
	response, err := c.request(ctx, method, path, body)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if err := responseError(response); err != nil {
		return err
	}
	if destination == nil || response.StatusCode == http.StatusNoContent {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, maxResponseBytes))
		return nil
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, maxResponseBytes+1))
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("decode Relay response: %w", err)
	}
	return nil
}

func (c *Client) request(ctx context.Context, method, path string, body any) (*http.Response, error) {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("encode Relay request: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return nil, fmt.Errorf("build Relay request: %w", err)
	}
	request.Header.Set("Authorization", "Bearer "+c.token)
	request.Header.Set("Accept", "application/json, image/png")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := c.http.Do(request)
	if err != nil {
		return nil, fmt.Errorf("call Relay desktop: %w", err)
	}
	return response, nil
}

func responseError(response *http.Response) error {
	if response.StatusCode >= 200 && response.StatusCode < 300 {
		return nil
	}
	document := struct {
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}{}
	_ = json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(&document)
	if document.Error.Code == "" {
		document.Error.Code = "HTTP_ERROR"
	}
	if document.Error.Message == "" {
		document.Error.Message = response.Status
	}
	return &APIError{Status: response.StatusCode, Code: document.Error.Code, Message: document.Error.Message}
}

func readLimited(reader io.Reader, limit int64) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(reader, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > limit {
		return nil, fmt.Errorf("Relay response exceeds %d bytes", limit)
	}
	return data, nil
}
