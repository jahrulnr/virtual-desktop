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

func TestWaitGoesThroughRelaySoHumanPreemptionCanCancelIt(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")

	result, err := service.Execute(context.Background(), Input{Action: "wait", Duration: 0.25})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != "Waited 0.250 seconds." {
		t.Fatalf("text = %q", result.Text)
	}
	if len(backend.actions) != 1 || backend.actions[0].Type != "wait" || backend.actions[0].DurationMS != 250 {
		t.Fatalf("actions = %+v", backend.actions)
	}
}

func TestClickWithoutCoordinateActsAtCurrentPointer(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 40, Y: 50}}
	service := NewService(backend, "coddy-session")

	result, err := service.Execute(context.Background(), Input{Action: "left_click"})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != "left click at the current pointer." {
		t.Fatalf("text = %q", result.Text)
	}
	if len(backend.actions) != 1 || backend.actions[0].Type != "click" {
		t.Fatalf("actions = %+v", backend.actions)
	}
}

func TestSmoothMoveSkipsWhenPointerIsAlreadyThere(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 20, Y: 30}}
	service := NewService(backend, "coddy-session")

	_, err := service.Execute(context.Background(), Input{
		Action:     "mouse_move",
		Coordinate: []int{20, 30},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(backend.actions) != 0 {
		t.Fatalf("actions = %+v", backend.actions)
	}
	if backend.claims != 0 {
		t.Fatalf("claims = %d", backend.claims)
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

func TestKeyAliasesResolveToCanonicalKeysyms(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")

	result, err := service.Execute(context.Background(), Input{Action: "key", Key: "ctrl+shift+t"})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != "Pressed ctrl+shift+t." {
		t.Fatalf("text = %q", result.Text)
	}
	last := backend.actions[len(backend.actions)-1]
	if len(last.Keys) != 3 || last.Keys[0] != "ctrl" || last.Keys[1] != "shift" || last.Keys[2] != "t" {
		t.Fatalf("keys = %v", last.Keys)
	}
}

func TestNaturalKeyNamesResolveThroughAliases(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")

	for _, input := range []struct {
		sent  string
		want  string
	}{
		{"enter", "Return"},
		{"Enter", "Return"},
		{"esc", "Escape"},
		{"pgup", "Prior"},
		{"backspace", "BackSpace"},
		{"f5", "F5"},
	} {
		_, err := service.Execute(context.Background(), Input{Action: "key", Key: input.sent})
		if err != nil {
			t.Fatalf("key %q: %v", input.sent, err)
		}
		last := backend.actions[len(backend.actions)-1]
		if len(last.Keys) != 1 || last.Keys[0] != input.want {
			t.Fatalf("key %q resolved to %v, want %q", input.sent, last.Keys, input.want)
		}
	}
}

func TestRejectsUnknownKeysymNames(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")

	// xdotool exits 0 for unknown key names; the service must reject them
	// up front so agents cannot be told a keypress succeeded silently.
	for _, bad := range []string{"enterx", "Hyper_L", "NonExistentKey"} {
		_, err := service.Execute(context.Background(), Input{Action: "key", Key: bad})
		if err == nil {
			t.Fatalf("key %q unexpectedly accepted", bad)
		}
	}
	_, err := service.Execute(context.Background(), Input{Action: "hold_key", Key: "fake_key", Duration: 0.5})
	if err == nil {
		t.Fatal("hold_key with an unknown name unexpectedly accepted")
	}
	if len(backend.actions) != 0 {
		t.Fatalf("actions = %+v", backend.actions)
	}
}
