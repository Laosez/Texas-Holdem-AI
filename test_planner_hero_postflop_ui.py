"""Screen 2 hero preflop/postflop distinct controls; V2 visible immediately."""
import unittest
from html.parser import HTMLParser

import planner_postflop_ev
import replit_simulator as app


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids={}
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if "id" in data:
            self.ids[data["id"]]=(tag,data)


class HeroPostflopChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page=app.PLAN_UI.read_text(encoding="utf-8")

    def test_v2_immediately_below_preflop_range_in_my_strategy(self):
        p=self.page
        heading=p.index('<section class="panel plannerStrategyPanel">')
        opponent=p.index('<section class="panel plannerOpponentsPanel">')
        own=p[heading:opponent]
        pre=own.index('id="heroProfile"')
        post=own.index('id="heroPostflop"')
        pos=own.index('id="heroPosition"')
        self.assertLess(pre,post)
        self.assertLess(post,pos)
        self.assertIn('Префлоп · диапазон / пресет',own)
        self.assertIn('Постфлоп · моя стратегия розыгрыша',own)
        self.assertIn('<option value="gto2" selected>GTO V2 · исправленные мелкие пары</option>',own)
        self.assertIn('id="heroStrategyComposition"',own)
        self.assertIn('id="heroPostflopHint"',own)
        ids=_Ids();ids.feed(p)
        for key in ('heroProfile','heroPostflop','heroStrategyComposition',
                    'heroPostflopHint','computeAll'):
            self.assertIn(key,ids.ids)
        self.assertEqual(p.count('id="heroPostflop"'),1)

    def test_selection_changes_ev_request_and_survives_reload(self):
        p=self.page
        self.assertIn("hero_postflop:$('heroPostflop').value",p)
        self.assertEqual(planner_postflop_ev.PROFILE_NAMES['gto2'],'gto_postflop_v2')
        self.assertIn("localStorage.getItem('skachkov_hero_postflop')",p)
        self.assertIn("localStorage.setItem('skachkov_hero_postflop'",p)
        self.assertIn("else $('heroPostflop').value='gto2';",p)
        self.assertIn("refreshHeroPostflopChoice();",p)
        self.assertIn("function refreshHeroPostflopChoice(){",p)
        self.assertIn("Сборка для EV:",p)
        self.assertIn("refreshHeroPostflopChoice();\n invalidateEquity();",p)
        self.assertIn("postflop.onchange=()=>{opponents[i].postflop=postflop.value;",p)

    def test_hero_v2_visible_in_narrow_33_percent_panel(self):
        p=self.page
        self.assertIn('.plannerStrategyPanel .heroPostflopChoice{',p)
        self.assertIn('.plannerStrategyPanel .heroPostflopChoice select{',p)
        self.assertIn('main.plannerMain{grid-template-columns:minmax(0,1fr) minmax(0,2fr)',p)
        self.assertIn('GTO V1 · контрольная версия',p)
        self.assertIn("{value:'gto',label:'GTO V1'}",p)
        self.assertIn("{value:'gto2',label:'GTO V2'}",p)


if __name__=="__main__":
    unittest.main()
