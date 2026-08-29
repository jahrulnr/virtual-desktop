package mcpserver

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/relay-ai/desktop/computer-mcp/internal/computer"
	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

type fakeBackend struct{}

func (fakeBackend) Apply(context.Context, string, []relay.Action) error { return nil }
func (fakeBackend) Heartbeat(context.Context, string) error             { return nil }
func (fakeBackend) Screenshot(context.Context) ([]byte, error) {
	return []byte("\x89PNG\r\n\x1a\nimage"), nil
}
func (fakeBackend) Accessibility(context.Context) ([]byte, error) {
	return []byte(`{"role":"desktop frame","children":[]}`), nil
}
func (fakeBackend) Cursor(context.Context) (relay.CursorPosition, error) {
	return relay.CursorPosition{X: 10, Y: 20}, nil
}
func (fakeBackend) Release(context.Context, string) error { return nil }
func (fakeBackend) ControlState(context.Context) ([]byte, error) {
	return []byte(`{"status":"ok","control":{"owner":"none"}}`), nil
}
func (fakeBackend) StartRecording(context.Context) ([]byte, error) {
	return []byte(`{"active":true}`), nil
}
func (fakeBackend) StopRecording(context.Context, bool) ([]byte, error) {
	return []byte(`{"status":"saved"}`), nil
}
func (fakeBackend) ListTerminals(context.Context) ([]byte, error) {
	return []byte(`{"sessions":[]}`), nil
}
func (fakeBackend) CreateTerminal(context.Context, string, string) ([]byte, error) {
	return []byte(`{"name":"demo"}`), nil
}
func (fakeBackend) TerminalCapture(context.Context, string) ([]byte, error) {
	return []byte(`{"output":"demo"}`), nil
}
func (fakeBackend) TerminalSend(context.Context, string, string, bool) ([]byte, error) {
	return []byte(`{"bytesSent":1}`), nil
}
func (fakeBackend) DestroyTerminal(context.Context, string) ([]byte, error) {
	return []byte(`{"status":"destroyed"}`), nil
}

func TestComputerToolReturnsMCPImageContent(t *testing.T) {
	ctx := context.Background()
	server := New(computer.NewService(fakeBackend{}, "coddy-test"))
	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "v1"}, nil)
	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer serverSession.Close()
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer clientSession.Close()

	result, err := clientSession.CallTool(ctx, &mcp.CallToolParams{
		Name:      "computer",
		Arguments: map[string]any{"action": "screenshot"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Content) != 2 {
		t.Fatalf("content length = %d", len(result.Content))
	}
	image, ok := result.Content[1].(*mcp.ImageContent)
	if !ok || image.MIMEType != "image/png" || string(image.Data[:8]) != "\x89PNG\r\n\x1a\n" {
		t.Fatalf("image content = %#v", result.Content[1])
	}
}

func TestUIInspectReturnsAccessibilityJSON(t *testing.T) {
	ctx := context.Background()
	server := New(computer.NewService(fakeBackend{}, "coddy-test"))
	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "v1"}, nil)
	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer serverSession.Close()
	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer clientSession.Close()

	result, err := clientSession.CallTool(ctx, &mcp.CallToolParams{Name: "ui_inspect", Arguments: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	text, ok := result.Content[0].(*mcp.TextContent)
	if !ok || text.Text != `{"role":"desktop frame","children":[]}` {
		t.Fatalf("content = %#v", result.Content)
	}
}

func TestHTTPTransportIsStateless(t *testing.T) {
	ctx := context.Background()
	httpServer := httptest.NewServer(NewHTTPHandler(computer.NewService(fakeBackend{}, "coddy-test")))
	defer httpServer.Close()

	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "v1"}, nil)
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: httpServer.URL}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	if session.ID() != "" {
		t.Fatalf("stateless transport returned session ID %q", session.ID())
	}

	for range 2 {
		result, err := session.CallTool(ctx, &mcp.CallToolParams{
			Name:      "computer",
			Arguments: map[string]any{"action": "cursor_position"},
		})
		if err != nil {
			t.Fatal(err)
		}
		if len(result.Content) != 1 {
			t.Fatalf("content length = %d", len(result.Content))
		}
	}
}

func TestExternalHandlerRejectsMissingOrWrongToken(t *testing.T) {
	handler := NewExternalHTTPHandler(computer.NewService(fakeBackend{}, "external-test"), "secret-token-0123456789")

	for _, header := range []string{"", "Bearer wrong-token", "secret-token-0123456789", "Basic secret-token-0123456789"} {
		req := httptest.NewRequest(http.MethodPost, "/mcp", nil)
		if header != "" {
			req.Header.Set("Authorization", header)
		}
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, req)
		if recorder.Code != http.StatusUnauthorized {
			t.Fatalf("Authorization %q returned %d, want 401", header, recorder.Code)
		}
		if recorder.Body.String() != `{"error":{"code":"UNAUTHORIZED","message":"valid MCP bearer token required"}}` {
			t.Fatalf("body = %q", recorder.Body.String())
		}
	}
}

func TestExternalHandlerAcceptsValidToken(t *testing.T) {
	ctx := context.Background()
	httpServer := httptest.NewServer(NewExternalHTTPHandler(computer.NewService(fakeBackend{}, "external-test"), "secret-token-0123456789"))
	defer httpServer.Close()

	transport := &mcp.StreamableClientTransport{Endpoint: httpServer.URL}
	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "v1"}, nil)

	// Without a token the handshake must fail with 401.
	if _, err := client.Connect(ctx, transport, nil); err == nil {
		t.Fatal("connection without a token unexpectedly succeeded")
	}

	authorized := mcp.StreamableClientTransport{Endpoint: httpServer.URL}
	authorized.HTTPClient = &http.Client{Transport: bearerTransport{token: "secret-token-0123456789"}}
	session, err := client.Connect(ctx, &authorized, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()

	result, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "runtime_status",
		Arguments: map[string]any{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Content) != 1 {
		t.Fatalf("content length = %d", len(result.Content))
	}
}

// bearerTransport adds the Authorization header to every request.
type bearerTransport struct {
	token string
}

func (b bearerTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	clone.Header.Set("Authorization", "Bearer "+b.token)
	return http.DefaultTransport.RoundTrip(clone)
}
