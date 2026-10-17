"""Visual contract for planner opponent grid, A17 palette, actions and EV review."""
import re
import unittest
import replit_simulator as app


class ScreenTwoVisualRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page=app.PLAN_UI.read_text(encoding="utf-8")
        cls.css=cls.page.split("<style>",1)[1].split("</style>",1)[0]

    def test_badge_css_is_not_swallowed_by_action_stripe(self):
        css=self.css
        # Regression: an unclosed actionStripe rule swallowed the handBoxTag
        # selector and its background, so badges appeared to lose their colors.
        self.assertIn(".matrixPane .actionStripe{height:4px;bottom:2px;left:2px;right:2px;opacity:.88}",css)
        self.assertEqual(css.count("{"),css.count("}"))
        self.assertRegex(css,r"(?s)\.matrixPane \.handBoxTag\{[^}]+background:var\(--group-color")
        self.assertIn('tag.style.setProperty(\'--group-color\',groupPaletteColor(b))',self.page)
        self.assertIn("card.style.setProperty('--group-color',groupPaletteColor(b));",self.page)
        self.assertIn("#groupEditor #boxes .boxSelect{",css)
        self.assertIn("background:var(--group-color,#8494a6)",css)
        self.assertIn("#groupEditor #boxes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))",css)

    def test_opponent_columns_are_bounded_and_shared_by_heading_and_rows(self):
        css=self.css
        self.assertIn(".plannerOpponentsPanel .oppTable .oppHead,",css)
        self.assertIn(".plannerOpponentsPanel .oppTable .oppRow{",css)
        self.assertIn("minmax(142px,174px)",css)
        self.assertIn("min-width:802px;align-items:start;width:100%",css)
        self.assertIn(".plannerOpponentsPanel .oppRow select{width:100%",css)
        self.assertIn(".plannerOpponentsPanel .oppTable .oppHead{overflow:visible}",css)
        self.assertIn("<span>Позиция №</span><span>Диапазон</span>",self.page)
        self.assertIn("min-width:860px;column-gap:8px;align-items:center",css)
        self.assertIn("<span>Постфлоп</span><span>Вероятность входа</span>",self.page)

    def test_sliders_match_four_action_stripe_colors(self):
        css=self.css
        colors={"fold":"#8995a2","open":"#e36b6e","limp":"#53b98b","call":"#63b2cf"}
        for kind,color in colors.items():
            with self.subTest(action=kind):
                self.assertIn(".actionStripe ."+("raise" if kind=="open" else kind)+"{background:"+color+"}",css)
                pattern=r"\.editorSection \.actionSliderField\[data-action="+kind+r"\][\s\S]{0,320}?--slider-color:"+re.escape(color)
                self.assertRegex(css,pattern)
        self.assertIn("background:linear-gradient(90deg,var(--slider-color)",css)
        self.assertIn("input.style.setProperty('--slider-percent',n+'%')",self.page)
        self.assertIn("input.style.setProperty('--slider-percent',values[key]+'%')",self.page)

    def test_strategy_ev_restores_four_metrics_and_candidate_frames(self):
        page=self.page
        self.assertIn("function strategyRangeEvBreakdown(doc,values){",page)
        self.assertIn("metric==='evStrategy'||metric==='evAllIn'",page)
        self.assertIn("strategyRangeEvBreakdown(hero,equityResults.filter?.ev_bb)",page)
        self.assertIn("for(const item of included.filter(x=>x.value < -threshold).slice(0,12))red.add(item.hand)",page)
        self.assertIn("for(const item of excluded.filter(x=>x.value > threshold).slice(0,12))gold.add(item.hand)",page)
        self.assertIn("if(candidates.gold.has(h))button.classList.add('candidateGold')",page)
        self.assertIn("if(candidates.red.has(h))button.classList.add('candidateRed')",page)
        for ident in ("rangeEvPlayed","rangeEvDealt","rangeEvNegative","rangeEvMissed"):
            self.assertIn('id="'+ident+'"',page)
        self.assertIn("pair('Postflop EV розыгрыша'",page)
        self.assertIn("pair('Дошли до вскрытия'",page)
        self.assertIn("pair('Выигрыш без вскрытия'",page)
        self.assertIn("ЖЁЛТАЯ рамка",page)
        self.assertIn("КРАСНАЯ — слабая включённая",page)


if __name__=="__main__":
    unittest.main()
