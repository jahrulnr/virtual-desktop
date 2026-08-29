package computer

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"strings"

	"github.com/relay-ai/desktop/computer-mcp/internal/relay"
)

type Relay interface {
	Apply(context.Context, string, []relay.Action) error
	Heartbeat(context.Context, string) error
	Screenshot(context.Context) ([]byte, error)
	Accessibility(context.Context) ([]byte, error)
	Cursor(context.Context) (relay.CursorPosition, error)
	Release(context.Context, string) error
	ControlState(context.Context) ([]byte, error)
	StartRecording(context.Context) ([]byte, error)
	StopRecording(context.Context, bool) ([]byte, error)
	ListTerminals(context.Context) ([]byte, error)
	CreateTerminal(context.Context, string, string) ([]byte, error)
	TerminalCapture(context.Context, string) ([]byte, error)
	TerminalSend(context.Context, string, string, bool) ([]byte, error)
	DestroyTerminal(context.Context, string) ([]byte, error)
}

type RecordInput struct {
	Mode string `json:"mode" jsonschema:"required,START_RECORDING, SAVE_RECORDING, or DISCARD_RECORDING"`
}

type TerminalInput struct {
	Action string `json:"action" jsonschema:"required,list, create, capture, send, or destroy"`
	Name   string `json:"name,omitempty" jsonschema:"terminal session name"`
	Text   string `json:"text,omitempty" jsonschema:"text to send for send action"`
	Cwd    string `json:"cwd,omitempty" jsonschema:"working directory for create action"`
	Enter  bool   `json:"enter,omitempty" jsonschema:"press Enter after send action"`
}

type Input struct {
	Action          string  `json:"action" jsonschema:"required,GUI action to perform"`
	Coordinate      []int   `json:"coordinate,omitempty" jsonschema:"optional target [x,y] in desktop pixels; omit to act at the current pointer"`
	StartCoordinate []int   `json:"start_coordinate,omitempty" jsonschema:"drag start [x,y] in desktop pixels"`
	Text            string  `json:"text,omitempty" jsonschema:"text to type at the focused control"`
	Key             string  `json:"key,omitempty" jsonschema:"key or plus-separated key combination such as ctrl+l"`
	Duration        float64 `json:"duration,omitempty" jsonschema:"duration in seconds, maximum 10"`
	ScrollDirection string  `json:"scroll_direction,omitempty" jsonschema:"up, down, left, or right"`
	ScrollAmount    int     `json:"scroll_amount,omitempty" jsonschema:"scroll detents from 1 to 10"`
}

type Result struct {
	Text     string
	PNG      []byte
	MIMEType string
}

type Service struct {
	relay   Relay
	agentID string
}

func NewService(backend Relay, agentID string) *Service {
	return &Service{relay: backend, agentID: agentID}
}

func (s *Service) Execute(ctx context.Context, input Input) (Result, error) {
	switch input.Action {
	case "screenshot":
		png, err := s.relay.Screenshot(ctx)
		return Result{Text: "Current desktop screenshot.", PNG: png, MIMEType: "image/png"}, err
	case "cursor_position":
		position, err := s.relay.Cursor(ctx)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: fmt.Sprintf("Cursor position: (%d, %d).", position.X, position.Y)}, nil
	case "mouse_move":
		target, err := coordinate(input.Coordinate, "coordinate")
		if err != nil {
			return Result{}, err
		}
		actions, err := s.smoothMove(ctx, target[0], target[1])
		if err != nil {
			return Result{}, err
		}
		if len(actions) > 0 {
			if err := s.relay.Apply(ctx, s.agentID, actions); err != nil {
				return Result{}, err
			}
		}
		return Result{Text: fmt.Sprintf("Mouse moved to (%d, %d).", target[0], target[1])}, nil
	case "left_click", "right_click", "middle_click", "double_click", "triple_click":
		return s.click(ctx, input)
	case "left_click_drag":
		start, err := coordinate(input.StartCoordinate, "start_coordinate")
		if err != nil {
			return Result{}, err
		}
		end, err := coordinate(input.Coordinate, "coordinate")
		if err != nil {
			return Result{}, err
		}
		action := relay.Action{Type: "drag", X: start[0], Y: start[1], ToX: end[0], ToY: end[1], Button: "left"}
		if err := s.relay.Apply(ctx, s.agentID, []relay.Action{action}); err != nil {
			return Result{}, err
		}
		return Result{Text: fmt.Sprintf("Dragged from (%d, %d) to (%d, %d).", start[0], start[1], end[0], end[1])}, nil
	case "left_mouse_down", "left_mouse_up":
		state := strings.TrimPrefix(input.Action, "left_mouse_")
		if err := s.relay.Apply(ctx, s.agentID, []relay.Action{{Type: "button", Button: "left", State: state}}); err != nil {
			return Result{}, err
		}
		return Result{Text: "Left mouse button " + state + "."}, nil
	case "type":
		if input.Text == "" || len(input.Text) > 4096 {
			return Result{}, fmt.Errorf("text must contain between 1 and 4096 bytes")
		}
		if err := s.relay.Apply(ctx, s.agentID, []relay.Action{{Type: "text", Text: input.Text}}); err != nil {
			return Result{}, err
		}
		return Result{Text: fmt.Sprintf("Typed %d characters.", len(input.Text))}, nil
	case "key":
		keys, err := keys(input.Key)
		if err != nil {
			return Result{}, err
		}
		if err := s.relay.Apply(ctx, s.agentID, []relay.Action{{Type: "key", Keys: keys}}); err != nil {
			return Result{}, err
		}
		return Result{Text: "Pressed " + strings.Join(keys, "+") + "."}, nil
	case "hold_key":
		parsed, err := keys(input.Key)
		if err != nil || len(parsed) != 1 {
			return Result{}, fmt.Errorf("hold_key requires one valid key name")
		}
		duration, err := durationMS(input.Duration)
		if err != nil {
			return Result{}, err
		}
		if err := s.relay.Apply(ctx, s.agentID, []relay.Action{{Type: "hold_key", Key: parsed[0], DurationMS: duration}}); err != nil {
			return Result{}, err
		}
		return Result{Text: fmt.Sprintf("Held %s for %.3f seconds.", parsed[0], input.Duration)}, nil
	case "scroll":
		return s.scroll(ctx, input)
	case "wait":
		if input.Duration == 0 {
			return Result{Text: "Waited 0.000 seconds."}, nil
		}
		duration, err := durationMS(input.Duration)
		if err != nil {
			return Result{}, err
		}
		if err := s.relay.Apply(ctx, s.agentID, []relay.Action{{Type: "wait", DurationMS: duration}}); err != nil {
			return Result{}, err
		}
		return Result{Text: fmt.Sprintf("Waited %.3f seconds.", input.Duration)}, nil
	case "release_control":
		if err := s.relay.Release(ctx, s.agentID); err != nil {
			return Result{}, err
		}
		return Result{Text: "Agent control released."}, nil
	default:
		return Result{}, fmt.Errorf("unsupported computer action %q", input.Action)
	}
}

func (s *Service) Inspect(ctx context.Context) (json.RawMessage, error) {
	data, err := s.relay.Accessibility(ctx)
	if err != nil {
		return nil, err
	}
	if !json.Valid(data) {
		return nil, fmt.Errorf("desktop returned invalid accessibility JSON")
	}
	return data, nil
}

func (s *Service) RuntimeStatus(ctx context.Context) (json.RawMessage, error) {
	data, err := s.relay.ControlState(ctx)
	if err != nil {
		return nil, err
	}
	if !json.Valid(data) {
		return nil, fmt.Errorf("desktop returned invalid runtime JSON")
	}
	return data, nil
}

func (s *Service) RecordScreen(ctx context.Context, input RecordInput) (Result, error) {
	switch input.Mode {
	case "START_RECORDING":
		data, err := s.relay.StartRecording(ctx)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: "Screen recording started. " + string(data)}, nil
	case "SAVE_RECORDING":
		data, err := s.relay.StopRecording(ctx, false)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: "Screen recording saved. " + string(data)}, nil
	case "DISCARD_RECORDING":
		data, err := s.relay.StopRecording(ctx, true)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: "Screen recording discarded. " + string(data)}, nil
	default:
		return Result{}, fmt.Errorf("mode must be START_RECORDING, SAVE_RECORDING, or DISCARD_RECORDING")
	}
}

func (s *Service) Terminal(ctx context.Context, input TerminalInput) (Result, error) {
	switch input.Action {
	case "list":
		data, err := s.relay.ListTerminals(ctx)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: string(data)}, nil
	case "create":
		if input.Name == "" {
			return Result{}, fmt.Errorf("name is required for create")
		}
		data, err := s.relay.CreateTerminal(ctx, input.Name, input.Cwd)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: string(data)}, nil
	case "capture":
		if input.Name == "" {
			return Result{}, fmt.Errorf("name is required for capture")
		}
		data, err := s.relay.TerminalCapture(ctx, input.Name)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: string(data)}, nil
	case "send":
		if input.Name == "" || input.Text == "" {
			return Result{}, fmt.Errorf("name and text are required for send")
		}
		data, err := s.relay.TerminalSend(ctx, input.Name, input.Text, input.Enter)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: string(data)}, nil
	case "destroy":
		if input.Name == "" {
			return Result{}, fmt.Errorf("name is required for destroy")
		}
		data, err := s.relay.DestroyTerminal(ctx, input.Name)
		if err != nil {
			return Result{}, err
		}
		return Result{Text: string(data)}, nil
	default:
		return Result{}, fmt.Errorf("action must be list, create, capture, send, or destroy")
	}
}

func (s *Service) click(ctx context.Context, input Input) (Result, error) {
	actions, target, err := s.moveToOptional(ctx, input.Coordinate, "coordinate")
	if err != nil {
		return Result{}, err
	}
	button, count := "left", 1
	switch input.Action {
	case "right_click":
		button = "right"
	case "middle_click":
		button = "middle"
	case "double_click":
		count = 2
	case "triple_click":
		count = 3
	}
	actions = append(actions, relay.Action{Type: "click", Button: button, Count: count})
	if err := s.relay.Apply(ctx, s.agentID, actions); err != nil {
		return Result{}, err
	}
	if target != nil {
		return Result{Text: fmt.Sprintf("%s at (%d, %d).", strings.ReplaceAll(input.Action, "_", " "), target[0], target[1])}, nil
	}
	return Result{Text: strings.ReplaceAll(input.Action, "_", " ") + " at the current pointer."}, nil
}

func (s *Service) scroll(ctx context.Context, input Input) (Result, error) {
	if input.ScrollAmount < 1 || input.ScrollAmount > 10 {
		return Result{}, fmt.Errorf("scroll_amount must be between 1 and 10")
	}
	if input.ScrollDirection != "up" && input.ScrollDirection != "down" && input.ScrollDirection != "left" && input.ScrollDirection != "right" {
		return Result{}, fmt.Errorf("scroll_direction must be up, down, left, or right")
	}
	actions, target, err := s.moveToOptional(ctx, input.Coordinate, "coordinate")
	if err != nil {
		return Result{}, err
	}
	actions = append(actions, relay.Action{Type: "scroll", Direction: input.ScrollDirection, Delta: input.ScrollAmount})
	if err := s.relay.Apply(ctx, s.agentID, actions); err != nil {
		return Result{}, err
	}
	if target != nil {
		return Result{Text: fmt.Sprintf("Scrolled %s by %d at (%d, %d).", input.ScrollDirection, input.ScrollAmount, target[0], target[1])}, nil
	}
	return Result{Text: fmt.Sprintf("Scrolled %s by %d at the current pointer.", input.ScrollDirection, input.ScrollAmount)}, nil
}

func (s *Service) moveToOptional(ctx context.Context, value []int, name string) ([]relay.Action, *[2]int, error) {
	if len(value) == 0 {
		return nil, nil, nil
	}
	target, err := coordinate(value, name)
	if err != nil {
		return nil, nil, err
	}
	actions, err := s.smoothMove(ctx, target[0], target[1])
	if err != nil {
		return nil, nil, err
	}
	return actions, &target, nil
}

func (s *Service) smoothMove(ctx context.Context, targetX, targetY int) ([]relay.Action, error) {
	position, err := s.relay.Cursor(ctx)
	if err != nil {
		return nil, err
	}
	distance := math.Hypot(float64(targetX-position.X), float64(targetY-position.Y))
	if distance < 1 {
		return nil, nil
	}
	steps := int(math.Ceil(distance / 32))
	if steps < 1 {
		steps = 1
	}
	if steps > 40 {
		steps = 40
	}
	actions := make([]relay.Action, 0, steps)
	for step := 1; step <= steps; step++ {
		progress := float64(step) / float64(steps)
		// Smoothstep avoids the robotic constant-velocity pointer motion.
		progress = progress * progress * (3 - 2*progress)
		x := position.X + int(math.Round(float64(targetX-position.X)*progress))
		y := position.Y + int(math.Round(float64(targetY-position.Y)*progress))
		actions = append(actions, relay.Action{Type: "move", X: x, Y: y})
	}
	return actions, nil
}

func coordinate(value []int, name string) ([2]int, error) {
	if len(value) != 2 || value[0] < 0 || value[1] < 0 {
		return [2]int{}, fmt.Errorf("%s must be a non-negative [x, y] pair", name)
	}
	return [2]int{value[0], value[1]}, nil
}

// keyAliases maps common LLM-friendly key names to canonical X11 keysyms.
var keyAliases = map[string]string{
	"enter":        "Return",
	"return":       "Return",
	"kp_enter":     "KP_Enter",
	"esc":          "Escape",
	"escape":       "Escape",
	"backspace":    "BackSpace",
	"delete":       "Delete",
	"del":          "Delete",
	"insert":       "Insert",
	"ins":          "Insert",
	"tab":          "Tab",
	"space":        "space",
	"pgup":         "Prior",
	"pageup":       "Prior",
	"prior":        "Prior",
	"pgdn":         "Next",
	"pgdown":       "Next",
	"home":         "Home",
	"end":          "End",
	"up":           "Up",
	"down":         "Down",
	"left":         "Left",
	"right":        "Right",
	"caps_lock":    "Caps_Lock",
	"capslock":     "Caps_Lock",
	"num_lock":     "Num_Lock",
	"numlock":      "Num_Lock",
	"scroll_lock":  "Scroll_Lock",
	"print":        "Print",
	"printscreen":  "Print",
	"prtsc":        "Print",
	"pause":        "Pause",
	"menu":         "Menu",
	"ctrl":         "ctrl",
	"alt":          "alt",
	"shift":        "shift",
	"super":        "super",
	"meta":         "super",
}

// keyModifiers are accepted in any case and passed to xdotool lowercase,
// which resolves both forms.
var keyModifiers = map[string]bool{
	"ctrl":  true,
	"alt":   true,
	"shift": true,
	"super": true,
}

// keySymbols is the allowlist of canonical keysyms verified against the
// container's xdotool build. Single alphanumeric characters are also
// valid printable keysyms and are accepted separately.
var keySymbols = map[string]bool{
	"Return": true, "KP_Enter": true, "Escape": true, "BackSpace": true,
	"Delete": true, "Insert": true, "Tab": true, "space": true,
	"Prior": true, "Next": true, "Home": true, "End": true,
	"Up": true, "Down": true, "Left": true, "Right": true,
	"Caps_Lock": true, "Num_Lock": true, "Scroll_Lock": true,
	"Print": true, "Pause": true, "Menu": true,
	"shift_r": true, "control_r": true, "alt_r": true, "super_r": true,
	"F1": true, "F2": true, "F3": true, "F4": true, "F5": true, "F6": true,
	"F7": true, "F8": true, "F9": true, "F10": true, "F11": true, "F12": true,
	"F13": true, "F14": true, "F15": true, "F16": true, "F17": true, "F18": true,
	"F19": true, "F20": true, "F21": true, "F22": true, "F23": true, "F24": true,
	"KP_Add": true, "KP_Subtract": true, "KP_Multiply": true, "KP_Divide": true,
	"KP_0": true, "KP_1": true, "KP_2": true, "KP_3": true, "KP_4": true,
	"KP_5": true, "KP_6": true, "KP_7": true, "KP_8": true, "KP_9": true,
}

// keyName resolves one plus-separated key name to a canonical keysym.
func keyName(value string) (string, error) {
	for _, character := range value {
		if !(character >= 'a' && character <= 'z') && !(character >= 'A' && character <= 'Z') && !(character >= '0' && character <= '9') && character != '_' {
			return "", fmt.Errorf("key names may contain only letters, numbers, and underscore")
		}
	}
	lowered := strings.ToLower(value)
	if keyModifiers[lowered] {
		return lowered, nil
	}
	if alias, ok := keyAliases[lowered]; ok {
		return alias, nil
	}
	for symbol := range keySymbols {
		if strings.ToLower(symbol) == lowered {
			return symbol, nil
		}
	}
	if len(value) == 1 {
		// Single characters are printable keysyms (a, L, 5).
		return value, nil
	}
	return "", fmt.Errorf("unknown key name %q; use canonical keysyms (Return, Escape, BackSpace, Up) or aliases (enter, esc, backspace, arrows)", value)
}

func keys(value string) ([]string, error) {
	parts := strings.Split(value, "+")
	if len(parts) < 1 || len(parts) > 5 {
		return nil, fmt.Errorf("key must contain between 1 and 5 plus-separated names")
	}
	for index, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			return nil, fmt.Errorf("key contains an empty name")
		}
		resolved, err := keyName(part)
		if err != nil {
			return nil, err
		}
		parts[index] = resolved
	}
	return parts, nil
}

func durationMS(seconds float64) (int, error) {
	if seconds <= 0 || seconds > 10 {
		return 0, fmt.Errorf("duration must be greater than 0 and at most 10 seconds")
	}
	return int(math.Round(seconds * 1000)), nil
}
