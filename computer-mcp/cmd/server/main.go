package main

import (
	"crypto/subtle"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/relay-ai/desktop/computer-mcp/internal/computer"
	"github.com/relay-ai/desktop/computer-mcp/internal/mcpserver"
	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

func main() {
	baseURL := envOr("RELAY_BASE_URL", "http://desktop:8080")
	operatorToken := os.Getenv("RELAY_OPERATOR_TOKEN")
	mcpToken := os.Getenv("MCP_AUTH_TOKEN")
	if len(mcpToken) < 16 {
		log.Fatal("MCP_AUTH_TOKEN must contain at least 16 characters")
	}
	client, err := relay.NewClient(baseURL, operatorToken, &http.Client{Timeout: 30 * time.Second})
	if err != nil {
		log.Fatal(err)
	}
	service := computer.NewService(client, envOr("RELAY_AGENT_ID", "coddy-agent"))
	server := mcpserver.New(service)
	mcpHandler := mcp.NewStreamableHTTPHandler(
		func(*http.Request) *mcp.Server { return server },
		&mcp.StreamableHTTPOptions{
			SessionTimeout:      30 * time.Minute,
			MaxRequestBodyBytes: 256 << 10,
		},
	)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.Handle("/mcp", bearer(mcpToken, mcpHandler))

	httpServer := &http.Server{
		Addr:              envOr("LISTEN_ADDR", ":8090"),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      2 * time.Minute,
		IdleTimeout:       2 * time.Minute,
	}
	log.Printf("relay computer MCP listening on %s", httpServer.Addr)
	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func bearer(token string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		expected := "Bearer " + token
		supplied := r.Header.Get("Authorization")
		if len(supplied) != len(expected) || subtle.ConstantTimeCompare([]byte(supplied), []byte(expected)) != 1 {
			w.Header().Set("WWW-Authenticate", `Bearer realm="relay-computer-mcp"`)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
