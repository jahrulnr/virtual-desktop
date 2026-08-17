package mcpserver

import (
	"context"
	"fmt"
	"net/http"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/relay-ai/desktop/computer-mcp/internal/computer"
)

type inspectInput struct{}

func New(service *computer.Service) *mcp.Server {
	server := mcp.NewServer(
		&mcp.Implementation{Name: "relay-computer", Version: "v0.1.0"},
		&mcp.ServerOptions{Instructions: "Operate the Relay Linux desktop. Observe before acting; human control always takes precedence."},
	)

	mcp.AddTool(server, &mcp.Tool{
		Name: "computer",
		Description: "Observe and control the shared Linux desktop using screenshots, smooth pointer movement, clicks, drag, typing, keys, scrolling, waits, and lease release. " +
			"Supported actions: screenshot, mouse_move, left_click, right_click, middle_click, double_click, triple_click, left_click_drag, left_mouse_down, left_mouse_up, cursor_position, type, key, hold_key, scroll, wait, release_control.",
		Annotations: &mcp.ToolAnnotations{Title: "Relay computer control", ReadOnlyHint: false},
	}, func(ctx context.Context, _ *mcp.CallToolRequest, input computer.Input) (*mcp.CallToolResult, any, error) {
		result, err := service.Execute(ctx, input)
		if err != nil {
			return nil, nil, err
		}
		content := []mcp.Content{&mcp.TextContent{Text: result.Text}}
		if len(result.PNG) > 0 {
			content = append(content, &mcp.ImageContent{Data: result.PNG, MIMEType: result.MIMEType})
		}
		return &mcp.CallToolResult{Content: content}, nil, nil
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "ui_inspect",
		Description: "Read a bounded AT-SPI accessibility snapshot for semantic grounding. Combine it with computer screenshot when labels or geometry are missing.",
		Annotations: &mcp.ToolAnnotations{Title: "Inspect desktop accessibility tree", ReadOnlyHint: true, IdempotentHint: true},
	}, func(ctx context.Context, _ *mcp.CallToolRequest, _ inspectInput) (*mcp.CallToolResult, any, error) {
		document, err := service.Inspect(ctx)
		if err != nil {
			return nil, nil, fmt.Errorf("inspect desktop UI: %w", err)
		}
		return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: string(document)}}}, nil, nil
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "runtime_status",
		Description: "Read the current desktop health, display size, control lease, and uptime.",
		Annotations: &mcp.ToolAnnotations{Title: "Read desktop runtime status", ReadOnlyHint: true, IdempotentHint: true},
	}, func(ctx context.Context, _ *mcp.CallToolRequest, _ inspectInput) (*mcp.CallToolResult, any, error) {
		document, err := service.RuntimeStatus(ctx)
		if err != nil {
			return nil, nil, fmt.Errorf("read runtime status: %w", err)
		}
		return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: string(document)}}}, nil, nil
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "record_screen",
		Description: "Record the shared desktop to MP4 in Downloads/recordings. Modes: START_RECORDING, SAVE_RECORDING, DISCARD_RECORDING.",
		Annotations: &mcp.ToolAnnotations{Title: "Record desktop screen", ReadOnlyHint: false},
	}, func(ctx context.Context, _ *mcp.CallToolRequest, input computer.RecordInput) (*mcp.CallToolResult, any, error) {
		result, err := service.RecordScreen(ctx, input)
		if err != nil {
			return nil, nil, err
		}
		return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: result.Text}}}, nil, nil
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "terminal",
		Description: "Manage bounded tmux terminal sessions for shell work. Actions: list, create, capture, send, destroy.",
		Annotations: &mcp.ToolAnnotations{Title: "Operate tmux terminal sessions", ReadOnlyHint: false},
	}, func(ctx context.Context, _ *mcp.CallToolRequest, input computer.TerminalInput) (*mcp.CallToolResult, any, error) {
		result, err := service.Terminal(ctx, input)
		if err != nil {
			return nil, nil, err
		}
		return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: result.Text}}}, nil, nil
	})

	return server
}

func NewHTTPHandler(service *computer.Service) http.Handler {
	return mcp.NewStreamableHTTPHandler(
		func(*http.Request) *mcp.Server { return New(service) },
		&mcp.StreamableHTTPOptions{
			Stateless:           true,
			MaxRequestBodyBytes: 256 << 10,
		},
	)
}
