package relay

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClientClaimsBeforeSendingInput(t *testing.T) {
	t.Helper()
	var paths []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if got := r.Header.Get("Authorization"); got != "Bearer operator-secret" {
			t.Fatalf("Authorization = %q", got)
		}
		if r.URL.Path == "/api/v1/input" {
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if body["agentId"] != "coddy-1" {
				t.Fatalf("agentId = %#v", body["agentId"])
			}
			w.WriteHeader(http.StatusNoContent)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"owner":"agent","ownerId":"coddy-1"}`))
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "operator-secret", server.Client())
	if err != nil {
		t.Fatal(err)
	}
	err = client.Apply(context.Background(), "coddy-1", []Action{{Type: "click", Button: "left"}})
	if err != nil {
		t.Fatal(err)
	}

	want := []string{"/api/v1/control/agent/claim", "/api/v1/input"}
	if len(paths) != len(want) || paths[0] != want[0] || paths[1] != want[1] {
		t.Fatalf("paths = %v, want %v", paths, want)
	}
}

func TestClientPreservesHumanControlConflict(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error":{"code":"CONTROL_CONFLICT","message":"human currently controls the desktop"}}`))
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "operator-secret", server.Client())
	if err != nil {
		t.Fatal(err)
	}
	err = client.Claim(context.Background(), "coddy-1")
	apiErr, ok := err.(*APIError)
	if !ok {
		t.Fatalf("error = %T %v, want *APIError", err, err)
	}
	if apiErr.Status != http.StatusConflict || apiErr.Code != "CONTROL_CONFLICT" {
		t.Fatalf("API error = %+v", apiErr)
	}
}

func TestClientReadsScreenshotAndCursor(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/screenshot":
			w.Header().Set("Content-Type", "image/png")
			_, _ = w.Write([]byte("\x89PNG\r\n\x1a\nimage"))
		case "/api/v1/cursor":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"x":12,"y":34,"screen":0,"window":99}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "operator-secret", server.Client())
	if err != nil {
		t.Fatal(err)
	}
	png, err := client.Screenshot(context.Background())
	if err != nil || string(png[:8]) != "\x89PNG\r\n\x1a\n" {
		t.Fatalf("screenshot = %q, err = %v", png, err)
	}
	position, err := client.Cursor(context.Background())
	if err != nil || position.X != 12 || position.Y != 34 {
		t.Fatalf("position = %+v, err = %v", position, err)
	}
}
