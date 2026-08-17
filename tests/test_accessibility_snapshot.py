import unittest

from desktop.control.a11y_snapshot import serialize_accessible


class FakeExtents:
    x = 12
    y = 34
    width = 200
    height = 40


class FakeComponent:
    def getExtents(self, _coordinates):
        return FakeExtents()


class FakeAction:
    nActions = 1

    def getName(self, _index):
        return "click"


class FakeStateSet:
    def __init__(self, states):
        self._states = states

    def getStates(self):
        return self._states


class FakeAccessible:
    def __init__(self, role, name, children=(), description="", states=()):
        self.role = role
        self.name = name
        self.description = description
        self.states = list(states)
        self.children = list(children)
        self.childCount = len(self.children)

    def getRoleName(self):
        return self.role

    def getDescription(self):
        return self.description

    def getState(self):
        return FakeStateSet(self.states)

    def getChildAtIndex(self, index):
        return self.children[index]

    def queryComponent(self):
        return FakeComponent()

    def queryAction(self):
        return FakeAction()


class AccessibilitySnapshotTests(unittest.TestCase):
    def test_serializes_roles_names_bounds_actions_and_children(self):
        root = FakeAccessible(
            "application",
            "Demo",
            [FakeAccessible("push button", "Save", description="Write the file", states=["STATE_FOCUSED"])],
            description="Main window",
            states=["STATE_SHOWING", "enabled"],
        )
        budget = {"remaining": 10}

        result = serialize_accessible(root, budget, desktop_coords=0)

        self.assertEqual(result["role"], "application")
        self.assertEqual(result["description"], "Main window")
        self.assertEqual(result["states"], ["showing", "enabled"])
        self.assertEqual(result["bounds"], {"x": 12, "y": 34, "width": 200, "height": 40})
        self.assertEqual(result["actions"], ["click"])
        self.assertEqual(result["children"][0]["name"], "Save")
        self.assertEqual(result["children"][0]["description"], "Write the file")
        self.assertEqual(result["children"][0]["states"], ["focused"])

    def test_respects_global_node_budget(self):
        root = FakeAccessible("desktop", "root", [FakeAccessible("app", str(i)) for i in range(5)])
        budget = {"remaining": 2}

        result = serialize_accessible(root, budget, desktop_coords=0)

        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(budget["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
