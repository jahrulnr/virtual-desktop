package computer

import (
	"context"
	"math"
	"strings"
	"testing"
	"unicode"

	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

type fakeRelay struct {
	actions []relay.Action
	batches [][]relay.Action
	claims  int
	png     []byte
	cursor  relay.CursorPosition
}

func (f *fakeRelay) Apply(_ context.Context, _ string, actions []relay.Action) error {
	f.claims++
	f.actions = append(f.actions, actions...)
	f.batches = append(f.batches, append([]relay.Action(nil), actions...))
	return nil
}
func (f *fakeRelay) Heartbeat(context.Context, string) error    { return nil }
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

func TestSmoothMouseMoveUsesPacedBlockingSteps(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 0, Y: 0}}
	service := NewService(backend, "coddy-session")

	_, err := service.Execute(context.Background(), Input{
		Action:     "mouse_move",
		Coordinate: []int{1200, 800},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(backend.actions) > 50 {
		t.Fatalf("generated %d actions, input batches are capped at 50", len(backend.actions))
	}
	waits := 0
	moves := 0
	for index, action := range backend.actions {
		switch action.Type {
		case "move":
			moves++
			if index > 0 && backend.actions[index-1].Type != "wait" && index != 0 {
				t.Fatalf("move at index %d was not paced: %+v", index, backend.actions)
			}
		case "wait":
			waits++
			if action.DurationMS <= 0 {
				t.Fatalf("wait = %+v, want a positive delay", action)
			}
		default:
			t.Fatalf("unexpected action = %+v", action)
		}
	}
	if moves < 2 || waits != moves-1 {
		t.Fatalf("moves = %d, waits = %d; want one wait between each move", moves, waits)
	}
	last := backend.actions[len(backend.actions)-1]
	if last.Type != "move" || last.X != 1200 || last.Y != 800 {
		t.Fatalf("last action = %+v", last)
	}
}

func TestPacedMoveUsesFrictionLikeAccelerationCurve(t *testing.T) {
	actions := pacedMove(0, 0, 400, 0, 10)
	wantX := []int{3, 23, 65, 127, 200, 273, 335, 377, 397, 400}
	moveIndex := 0
	for _, action := range actions {
		if action.Type != "move" {
			continue
		}
		if action.X != wantX[moveIndex] {
			t.Fatalf("move %d x = %d, want smootherstep position %d", moveIndex, action.X, wantX[moveIndex])
		}
		moveIndex++
	}
	if moveIndex != len(wantX) {
		t.Fatalf("moves = %d, want %d", moveIndex, len(wantX))
	}
	if math.Abs(frictionProgress(0)-0) > 1e-12 || math.Abs(frictionProgress(1)-1) > 1e-12 {
		t.Fatal("friction progress must start at 0 and finish at 1")
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
	click := backend.actions[len(backend.actions)-2]
	if click.Type != "click" || click.Button != "left" || click.Count != 2 {
		t.Fatalf("click action = %+v", click)
	}
	settle := backend.actions[len(backend.actions)-1]
	if settle.Type != "wait" || settle.DurationMS != 180 {
		t.Fatalf("settle action = %+v, want 180 ms wait", settle)
	}
}

func TestInteractiveActionsLeaveAReadableSettlePause(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 10, Y: 10}}
	service := NewService(backend, "coddy-session")

	if _, err := service.Execute(context.Background(), Input{Action: "left_click"}); err != nil {
		t.Fatal(err)
	}
	if len(backend.actions) != 2 {
		t.Fatalf("click actions = %+v, want click plus settle pause", backend.actions)
	}
	if backend.actions[0].Type != "click" || backend.actions[1].Type != "wait" || backend.actions[1].DurationMS != 180 {
		t.Fatalf("click actions = %+v, want 180 ms settle pause", backend.actions)
	}

	backend.actions = nil
	if _, err := service.Execute(context.Background(), Input{Action: "key", Key: "ctrl+l"}); err != nil {
		t.Fatal(err)
	}
	if len(backend.actions) != 2 {
		t.Fatalf("key actions = %+v, want key plus settle pause", backend.actions)
	}
	if backend.actions[0].Type != "key" || backend.actions[1].Type != "wait" || backend.actions[1].DurationMS != 180 {
		t.Fatalf("key actions = %+v, want 180 ms settle pause", backend.actions)
	}
}

func TestTypeStreamsHumanVisibleDeltas(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")
	text := strings.Repeat("Relay types this delta. ", 8)

	result, err := service.Execute(context.Background(), Input{Action: "type", Text: text})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != "Typed 192 characters." {
		t.Fatalf("text = %q", result.Text)
	}
	if len(backend.batches) < 2 {
		t.Fatalf("batches = %d, want multiple blocking deltas", len(backend.batches))
	}
	var combined strings.Builder
	for index, batch := range backend.batches {
		if len(batch) != 1 || batch[0].Type != "text" {
			t.Fatalf("batch %d = %+v, want one text delta", index, batch)
		}
		if len([]rune(batch[0].Text)) > 48 {
			t.Fatalf("batch %d contains too many characters: %d", index, len([]rune(batch[0].Text)))
		}
		combined.WriteString(batch[0].Text)
	}
	if combined.String() != text {
		t.Fatalf("combined text = %q, want %q", combined.String(), text)
	}
}

func TestTypePrefersWordBoundariesForDeltas(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")
	text := strings.Repeat("smooth human timing ", 8)

	if _, err := service.Execute(context.Background(), Input{Action: "type", Text: text}); err != nil {
		t.Fatal(err)
	}
	for index, batch := range backend.batches {
		if len(batch) != 1 || batch[0].Type != "text" {
			t.Fatalf("batch %d = %+v, want one text delta", index, batch)
		}
		if index == 0 {
			continue
		}
		previous := []rune(backend.batches[index-1][0].Text)
		current := []rune(batch[0].Text)
		if len(previous) == 0 || len(current) == 0 {
			t.Fatalf("empty delta at boundary %d: previous=%q current=%q", index, backend.batches[index-1][0].Text, batch[0].Text)
		}
		if !unicode.IsSpace(previous[len(previous)-1]) && !unicode.IsSpace(current[0]) {
			t.Fatalf("delta %d splits a word: previous=%q current=%q", index, backend.batches[index-1][0].Text, batch[0].Text)
		}
	}
}

func TestDragUsesPacedPathAndButtonTransitions(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 0, Y: 0}}
	service := NewService(backend, "coddy-session")

	_, err := service.Execute(context.Background(), Input{
		Action:          "left_click_drag",
		StartCoordinate: []int{20, 20},
		Coordinate:      []int{500, 400},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(backend.actions) > 50 {
		t.Fatalf("generated %d actions, input batches are capped at 50", len(backend.actions))
	}
	if backend.actions[len(backend.actions)-1].Type != "button" || backend.actions[len(backend.actions)-1].State != "up" {
		t.Fatalf("last action = %+v, want button up", backend.actions[len(backend.actions)-1])
	}
	waits := 0
	for _, action := range backend.actions {
		if action.Type == "drag" {
			t.Fatalf("drag should be expanded into paced actions: %+v", backend.actions)
		}
		if action.Type == "wait" {
			waits++
		}
	}
	if waits == 0 {
		t.Fatalf("actions = %+v, want paced drag movement", backend.actions)
	}
}

func TestLongDragStaysWithinInputBatchLimit(t *testing.T) {
	backend := &fakeRelay{cursor: relay.CursorPosition{X: 0, Y: 0}}
	service := NewService(backend, "coddy-session")

	_, err := service.Execute(context.Background(), Input{
		Action:          "left_click_drag",
		StartCoordinate: []int{700, 450},
		Coordinate:      []int{1439, 899},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(backend.actions) > 50 {
		t.Fatalf("generated %d actions, want at most 50", len(backend.actions))
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
	if len(backend.actions) != 2 || backend.actions[0].Type != "click" || backend.actions[1].Type != "wait" {
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
	keyAction := backend.actions[len(backend.actions)-2]
	if len(keyAction.Keys) != 3 || keyAction.Keys[0] != "ctrl" || keyAction.Keys[1] != "shift" || keyAction.Keys[2] != "t" {
		t.Fatalf("keys = %v", keyAction.Keys)
	}
}

func TestNaturalKeyNamesResolveThroughAliases(t *testing.T) {
	backend := &fakeRelay{}
	service := NewService(backend, "coddy-session")

	for _, input := range []struct {
		sent string
		want string
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
		keyAction := backend.actions[len(backend.actions)-2]
		if len(keyAction.Keys) != 1 || keyAction.Keys[0] != input.want {
			t.Fatalf("key %q resolved to %v, want %q", input.sent, keyAction.Keys, input.want)
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
