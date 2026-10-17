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

    def test_hero_controls_are_one_canonical_set_mounted_in_fixed_seat(self):
        p=self.page
        heading=p.index('<section class="panel plannerStrategyPanel">')
        opponent=p.index('<section class="panel plannerOpponentsPanel">')
        own=p[heading:opponent]
        self.assertIn('01 / </span>Версии стратегии',own)
        self.assertIn('id="heroControlDock" class="hidden"',own)
        self.assertIn('id="strategyName"',own)
        self.assertIn('id="save"',own)
        self.assertIn('<option value="gto2" selected>GTO V2',own)
        self.assertIn("function heroPositionSeatRow(position,controls){",p)
        self.assertIn("const heroControls={",p)
        self.assertIn("profile:$('heroProfile'),position:$('heroPosition')",p)
        self.assertIn("scenario:$('heroScenario'),postflop:$('heroPostflop')",p)
        self.assertIn("const target=$('opponents');target.replaceChildren();",p)
        self.assertIn("row.append(profile)",p)
        self.assertIn("row.append(pos)",p)
        self.assertIn("row.append(scenario)",p)
        self.assertIn("row.append(postflop)",p)
        self.assertIn("target.append(heroPositionSeatRow(heroSeat,heroControls));",p)
        self.assertIn("169 рук ↓",p)
        self.assertIn('Hero · выбранная рука',p)
        self.assertIn("scrollIntoView({behavior:'smooth',block:'start'})",p)
        ids=_Ids();ids.feed(p)
        for key in ('heroProfile','heroPostflop','heroPosition','heroScenario',
                    'heroStrategyComposition','heroPostflopHint','computeAll'):
            self.assertEqual(ids.ids.count(key),1)

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

    def test_hero_v2_visible_in_wide_opponent_panel(self):
        p=self.page
        self.assertIn(".plannerOpponentsPanel .oppHeroSeat select{",p)
        self.assertIn("main.plannerMain{grid-template-columns:minmax(275px,1fr) minmax(0,3fr)",p)
        self.assertIn("GTO V1 · контрольная версия",p)
        self.assertIn("{value:'gto',label:'GTO V1'}",p)
        self.assertIn("{value:'gto2',label:'GTO V2'}",p)
        self.assertIn("localStorage.getItem('skachkov_hero_postflop')",p)
