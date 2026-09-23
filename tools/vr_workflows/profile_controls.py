"""Profile-driven menu acquisition with independent hit metrics and retained misses."""
import json
import re
from copy import deepcopy
from pathlib import Path
from tools.vr_motion.metrics import target_metrics
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.control_approach import control_approach


def hover_label(label):
    return re.sub('_+', '_', label.lower().translate(str.maketrans({' ': '_', '/': '_', '+': '_'})))


def control_hit(state, label):
    control = next((c for c in state['controls'] if c['label'] == label), None)
    if control is None:
        return False
    metrics = target_metrics(control,state['hands'][1])
    if label in ('LATTICE EXIT','CENTER PAINT'):
        feedback = state.get('extrude',{}).get('open') and state['hands'][1].get('input_owner') == 'lattice'
    else:
        feedback = state['hover'] == hover_label(label)
    return bool(metrics['predicted_hit'] and feedback)


class ProfileControls:
    def __init__(self, live, output, preset, seed=0, feedback=False, approach=False):
        self.live = live
        self.output = Path(output)
        self.preset = preset
        self.seed = seed
        self.trials = []
        self.feedback = feedback
        self.approach = approach

    def click(self, label):
        """At most three feedback-directed reaches; never snap a noisy endpoint."""
        for attempt in range(1, 4):
            control = next((c for c in self.live.state['controls'] if c['label'] == label), None)
            if control is None:
                raise RuntimeError(f'Control unavailable: {label}')
            # Validate observability before moving: never silently idealize a control.
            target_metrics(control, self.live.state['hands'][1])
            options = {'acquired':lambda state: control_hit(state,label)} if self.feedback else {}
            if self.approach:
                options['target_position'] = control_approach(control,self.live.state['hands'][1]['position'])
            trial = reach_target(self.live, control['position'], self.preset, self.seed+len(self.trials), **options)
            current = next((c for c in self.live.state['controls'] if c['label'] == label), None)
            metrics = target_metrics(current, self.live.state['hands'][1]) if current else None
            tablet = label in ('LATTICE EXIT','CENTER PAINT')
            hit = control_hit(self.live.state,label) and (not self.feedback or trial['acquired_with_feedback'])
            trial.update(approach_policy='panel_normal_30cm_v1' if self.approach else 'stationary_aim',
                         label=label, attempt=attempt, target_geometry=current,
                         metrics=metrics, hover=self.live.state['hover'], clicked=hit)
            self.trials.append(trial)
            self._save()
            if hit:
                before = {k:self.live.state.get(k) for k in ['menu','status','config_sequence','tool_sequence']}
                before_tablet = deepcopy(self.live.state.get('extrude',{}))
                self.live.button('trigger')
                self.live.frame()
                trial['before_click'] = before
                trial['after_click'] = {k:self.live.state.get(k) for k in before}
                if tablet:
                    trial['tablet_before'] = before_tablet
                    trial['tablet_after'] = deepcopy(self.live.state['extrude'])
                self._save()
                if label == 'LATTICE EXIT' and self.live.state['extrude']['open']:
                    raise RuntimeError('Tablet Exit did not close paint')
                if label == 'CENTER PAINT' and (not self.live.state['extrude']['open'] or
                        self.live.state['extrude']['cells'] != before_tablet['cells']):
                    raise RuntimeError('Center Paint changed the draft instead of its view')
                return trial
        raise RuntimeError(f'Profile control acquisition failed after three reaches: {label}')

    def _save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(self.trials, indent=2)+'\n')
