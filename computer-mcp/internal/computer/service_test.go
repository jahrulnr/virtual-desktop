package computer

import (
	"context"
	"testing"

	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

type fakeRelay struct {
	actions []relay.Action
	claims  int
	png     []byte
	cursor  relay.CursorPosition
}

func (f *fakeRelay) Apply(_ context.Context, _ string, actions []relay.Action) error {
	f.claims++
	f.actions = append(f.actions, actions...)
	return nil
}
func (f *fakeRelay) Heartbeat(context.Context, string) error { return nil }
func (f *fakeRelay) Screenshot(context.Context) ([]byte, error) { return f.png, nil }
func (f *fakeRelay) Accessibility(context.Context) ([]byte, error) {
	return []byte(`{"role":"desktop frame"}`), nil
}
func (f *fakeRelay) Cursor(context.Context) (relay.CursorPosition, error) { return f.cursor, nil }
func (f *fakeRelay) Release(context.Context, string) error                { return nil }
func (f *fakeRelay) ControlState(context.Context) ([]byte, error) {
	return []byte(`{"status":"ok"}`), nil
}
func (f *fakeRelay) StartRecording(context.Context) ([]byte, error) {
	return []byte(`{"active":true}`), nil
}
func (f *fakeRelay) StopRecording(context.Context, bool) ([]byte, error) {
	return []byte(`{"status":"saved"}`), nil
}
func (f *fakeRelay) ListTerminals(context.Context) ([]byte, error) {
	return []byte(`{"sessions":[]}`), nil
}
func (f *fakeRelay) CreateTerminal(context.Context, string, string) ([]byte, error) {
	return []byte(`{"name":"demo"}`), nil
}
func (f *fakeRelay) TerminalCapture(context.Context, string) ([]byte, error) {
	return []byte(`{"output":"demo"}`), nil
}
func (f *fakeRelay) TerminalSend(context.Context, string, string, bool) ([]byte, error) {
	return []byte(`{"bytesSent":1}`), nil
}
func (f *fakeRelay) DestroyTerminal(context.Context, string) ([]byte, error) {
	return []byte(`{"status":"destroyed"}`), nil
}

func TestSmoothMouseMoveInterpolatesFromRealCursor(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 0, Y: 0}}
	service := NewService(backend, "coddy-session")

	result, err := service.Execute(context.Background(), Input{
		Action:     "mouse_move",
		Coordinate: []int{120, 60},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != "Mouse moved to (120, 60)." {
		t.Fatalf("text = %q", result.Text)
	}
	if len(backend.actions) < 2 || len(backend.actions) > 40 {
		t.Fatalf("generated %d move actions", len(backend.actions))
	}
	last := backend.actions[len(backend.actions)-1]
	if last.Type != "move" || last.X != 120 || last.Y != 60 {
		t.Fatalf("last action = %+v", last)
	}
}

func TestClickMovesThenClicksAndUsesOneLeaseClaim(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 10, Y: 10}}
	service := NewService(backend, "coddy-session")

	_, err := service.Execute(context.Background(), Input{
		Action:     "double_click",
		Coordinate: []int{20, 30},
	})
	if err != nil {
		t.Fatal(err)
	}
	if backend.claims != 1 {
		t.Fatalf("claims = %d, want 1", backend.claims)
	}
	last := backend.actions[len(backend.actions)-1]
	if last.Type != "click" || last.Button != "left" || last.Count != 2 {
		t.Fatalf("last action = %+v", last)
	}
}

func TestScreenshotIsReturnedAsImageObservation(t *testing.T) {
	backend := &fakeRelay{png: []byte("\x89PNG\r\n\x1a\nimage")}
	service := NewService(backend, "coddy-session")

	result, err := service.Execute(context.Background(), Input{Action: "screenshot"})
	if err != nil {
		t.Fatal(err)
	}
	if string(result.PNG) != string(backend.png) || result.MIMEType != "image/png" {
		t.Fatalf("result = %+v", result)
	}
}

func TestRejectsInvalidCoordinatesBeforeCallingDesktop(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")

	_, err := service.Execute(context.Background(), Input{Action: "left_click", Coordinate: []int{1}})
	if err == nil {
		t.Fatal("expected coordinate validation error")
	}
	if backend.claims != 0 {
		t.Fatalf("claims = %d", backend.claims)
	}
}
