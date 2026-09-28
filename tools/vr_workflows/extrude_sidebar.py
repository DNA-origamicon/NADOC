"""Real controller navigation for the dedicated Extrude sidebar."""
from tools.vr_workflows.menu_tour import click, scroll_page

class SidebarControls:
    def __init__(self, live, output, preset):
        self.live,self.output,self.preset=live,output,preset
        self.trials=[]
        self.checked_exit=False
    def click(self, identifier):
        import json
        live=self.live
        if not any(c.get('id')==identifier for c in live.state['controls']):
            while live.state['sidebars'][1]['offset']>0:scroll_page(live,1,-1)
        for attempt in range(100):
            if any(c.get('id')==identifier for c in live.state['controls']):
                click(live,1,identifier,self.preset,self.trials)
                (self.output/'sidebar-reaches.json').write_text(json.dumps(self.trials,indent=2))
                return
            before=live.state['sidebars'][1]['offset']
            scroll_page(live,1,1)
            if live.state['sidebars'][1]['offset']==before:break
        raise RuntimeError('Missing sidebar control: '+identifier)
    def activate(self):
        live=self.live
        if live.state['sidebars'][1]['tab']=='extrude':
            self.click('extrude:back')
        if not live.state['sidebars'][1]['open']:
            live.button('menu',hand=1);live.frame()
        self.click('tab:tools')
        self.click('tool-extrude')
        assert live.state['sidebars'][1]['tab']=='extrude'
        assert live.state['extrude']['open']
        assert live.state['sidebars'][1]['layout']=='valid'
        if not self.checked_exit:
            self.checked_exit=True
            self.click('extrude:cancel')
            assert not live.state['extrude']['open'] and live.state['sidebars'][1]['tab']=='tools'
            self.click('tool-extrude')
            from tools.vr_workflows.profile_controls import ProfileControls
            exit_control=ProfileControls(live,self.output/'exit-reach.json',self.preset,15000,feedback=True,approach=True)
            exit_control.click('LATTICE EXIT')
            assert not live.state['extrude']['open'] and live.state['sidebars'][1]['tab']=='tools'
            self.click('tool-extrude')
            assert live.state['extrude']['open'] and live.state['sidebars'][1]['tab']=='extrude'
        live.capture_to(self.output/f'extrude-sidebar-{len(self.trials)}',discard_source=True)
