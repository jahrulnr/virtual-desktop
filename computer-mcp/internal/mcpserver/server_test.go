package mcpserver

import (
	"context"
	"net/http/httptest"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/relay-ai/desktop/computer-mcp/internal/computer"
	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

type fakeBackend struct{}

func (fakeBackend) Apply(context.Context, string, []relay.Action) error { return nil }
func (fakeBackend) Heartbeat(context.Context, string) error               { return nil }
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
