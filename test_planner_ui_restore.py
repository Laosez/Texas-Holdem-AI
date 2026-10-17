"""Prevent regression of Screen 2 layout, range colors and A17 bulk controls."""
import re
import unittest
from html.parser import HTMLParser
import replit_simulator as app


class _PlannerStructure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.parents = {}
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.parents[d["id"]] = tuple(self.stack)
        if tag not in ("input", "meta", "link", "hr", "img", "br", "source", "area", "wbr"):
            self.stack.append((tag, d.get("class", "")))
    def handle_endtag(self, tag):
        if tag in ("input", "meta", "link", "hr", "img", "br", "source", "area", "wbr"):
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                return


class PlannerLayoutRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = app.PLAN_UI.read_text(encoding="utf-8")

    def test_first_two_blocks_and_equity_under_opponents_only(self):
        page = self.ui
        first = page.index('<section class="panel plannerOpponentsPanel">')
        second = page.index('<section class="panel plannerStrategyPanel">')
        workspace = page.index('<div class="plannerWorkspace">')
        self.assertLess(first, second)
        self.assertLess(second, workspace)
        self.assertIn('Мои соперники', page[first:second])
        self.assertIn('Версии стратегии', page[second:workspace])
        self.assertNotIn('id="opponents"', page[second:workspace])
        self.assertIn('id="opponents"', page[first:second])
        self.assertIn('id="computeAll"', page[first:second])
        self.assertEqual(page.count('id="computeAll"'), 1)
        self.assertEqual(page.count('id="equityModel"'), 1)
        self.assertIn('<option value="selected" selected>', page)
        self.assertNotIn('<option value="any_two">', page)
        self.assertNotIn('<option value="gto_heuristic">', page)
        self.assertIn('main.plannerMain{grid-template-columns:minmax(0,1fr);align-items:start}', page)
        self.assertIn('.plannerMain>.plannerWorkspace{grid-column:1/-1;min-width:0}', page)
        self.assertNotIn('plannerEquityPanel', page)

        parser = _PlannerStructure()
        parser.feed(page)
        for name in ("heroProfile", "opponents", "computeAll", "heroMatrix", "boxes"):
            self.assertIn(name, parser.parents)
        opp_ancestors = parser.parents["computeAll"]
        self.assertTrue(any("plannerOpponentsPanel" in c for _, c in opp_ancestors))
        self.assertTrue(any("plannerOpponentsPanel" in c for _, c in parser.parents["opponents"]))
        self.assertFalse(any("plannerStrategyPanel" in c for _, c in parser.parents["opponents"]))

    def test_single_matrix_blue_membership_and_colored_a17_tags(self):
        page=self.ui
        self.assertIn("const showIntersection=false;",page)
        self.assertNotIn('<details id="villainPane"',page)
        self.assertIn("background:#365b76!important;",page)
        self.assertIn(".matrixGrid .hand.playedRange",page)
        self.assertIn("tag.style.setProperty('--group-color',groupPaletteColor(b))",page)
        self.assertIn("background:var(--group-color,#8494a6)!important",page)
        self.assertIn("z-index:9!important",page)

    def test_four_box_columns_multiselect_and_bulk_action(self):
        page = self.ui
        self.assertIn('id="groupEditor" class="groupDrawer groupEditor"><summary>', page)
        self.assertIn(".unifiedGroupList .boxList{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))", page)
        self.assertIn("if(wasSelected)selectedBoxes.delete(b);else selectedBoxes.add(b);", page)
        self.assertIn("if(selectedBoxes.size&&hero)return HANDS.filter(h=>selectedBoxes.has(hero.boxes?.[h]));", page)
        self.assertIn("for(const h of targets)hero.hands[h]={...actions};", page)
        self.assertIn("selectedBoxes.size?'ВЫБРАННЫЕ КОРОБКИ'", page)
        self.assertIn(".editorSection .actionGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))", page)
        self.assertIn("input.type='range';input.min='0';input.max='100';input.step='25';", page)

    def test_remembers_chosen_saved_strategy_without_touching_storage_backend(self):
        page = self.ui
        self.assertIn("localStorage.getItem('skachkov_last_plan_profile')", page)
        self.assertIn("localStorage.setItem('skachkov_last_plan_profile'", page)
        self.assertEqual(page.count('id="heroProfile"'),1)


if __name__ == "__main__":
    unittest.main()
