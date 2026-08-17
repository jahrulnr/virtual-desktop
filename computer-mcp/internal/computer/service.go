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
	Screenshot(context.Context) ([]byte, error)
	Accessibility(context.Context) ([]byte, error)
	Cursor(context.Context) (relay.CursorPosition, error)
	Release(context.Context, string) error
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
		for _, character := range part {
			if !(character >= 'a' && character <= 'z') && !(character >= 'A' && character <= 'Z') && !(character >= '0' && character <= '9') && character != '_' {
				return nil, fmt.Errorf("key names may contain only letters, numbers, and underscore")
			}
		}
		parts[index] = strings.ToUpper(part)
	}
	return parts, nil
}

func durationMS(seconds float64) (int, error) {
	if seconds <= 0 || seconds > 10 {
		return 0, fmt.Errorf("duration must be greater than 0 and at most 10 seconds")
	}
	return int(math.Round(seconds * 1000)), nil
}
