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


class FakeAccessible:
    def __init__(self, role, name, children=()):
        self.role = role
        self.name = name
        self.children = list(children)
        self.childCount = len(self.children)

    def getRoleName(self):
        return self.role

    def getChildAtIndex(self, index):
        return self.children[index]

    def queryComponent(self):
        return FakeComponent()

    def queryAction(self):
        return FakeAction()


class AccessibilitySnapshotTests(unittest.TestCase):
    def test_serializes_roles_names_bounds_actions_and_children(self):
        root = FakeAccessible(
            "application", "Demo", [FakeAccessible("push button", "Save")]
        )
        budget = {"remaining": 10}

        result = serialize_accessible(root, budget, desktop_coords=0)

        self.assertEqual(result["role"], "application")
        self.assertEqual(result["bounds"], {"x": 12, "y": 34, "width": 200, "height": 40})
        self.assertEqual(result["actions"], ["click"])
        self.assertEqual(result["children"][0]["name"], "Save")

    def test_respects_global_node_budget(self):
        root = FakeAccessible("desktop", "root", [FakeAccessible("app", str(i)) for i in range(5)])
        budget = {"remaining": 2}

        result = serialize_accessible(root, budget, desktop_coords=0)

        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(budget["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
