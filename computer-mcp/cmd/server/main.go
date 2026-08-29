package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"github.com/relay-ai/desktop/computer-mcp/internal/computer"
	"github.com/relay-ai/desktop/computer-mcp/internal/mcpserver"
	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

func main() {
	baseURL := envOr("RELAY_BASE_URL", "http://127.0.0.1:8080")
	operatorToken := os.Getenv("RELAY_OPERATOR_TOKEN")
	client, err := relay.NewClient(baseURL, operatorToken, &http.Client{Timeout: 45 * time.Second})
	if err != nil {
		log.Fatal(err)
	}
	service := computer.NewService(client, envOr("RELAY_AGENT_ID", "coddy-agent"))

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.Handle("/mcp", mcpserver.NewHTTPHandler(service))

	httpServer := &http.Server{
		Addr:              envOr("LISTEN_ADDR", "127.0.0.1:8090"),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      2 * time.Minute,
		IdleTimeout:       2 * time.Minute,
	}
	log.Printf("relay computer MCP listening on %s", httpServer.Addr)

	// Optional external listener for agents outside the desktop container.
	// It requires its own bearer token and never shares the internal,
	// token-free listener used by the pinned Coddy configuration.
	if external := os.Getenv("RELAY_MCP_EXTERNAL_LISTEN"); external != "" {
		token := os.Getenv("RELAY_MCP_TOKEN")
		if len(token) < 16 {
			log.Fatal("RELAY_MCP_EXTERNAL_LISTEN requires RELAY_MCP_TOKEN of at least 16 characters")
		}
		externalMux := http.NewServeMux()
		externalMux.Handle("GET /healthz", mcpserver.BearerAuth(
			http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.Header().Set("Cache-Control", "no-store")
				_, _ = w.Write([]byte(`{"status":"ok"}`))
			}), token))
		externalMux.Handle("/mcp", mcpserver.NewExternalHTTPHandler(service, token))
		externalServer := &http.Server{
			Addr:              external,
			Handler:           externalMux,
			ReadHeaderTimeout: 5 * time.Second,
			ReadTimeout:       30 * time.Second,
			WriteTimeout:      2 * time.Minute,
			IdleTimeout:       2 * time.Minute,
		}
		log.Printf("relay computer MCP external listener on %s (bearer token required)", external)
		go func() {
			if err := externalServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				log.Fatal(err)
			}
		}()
	}

	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
