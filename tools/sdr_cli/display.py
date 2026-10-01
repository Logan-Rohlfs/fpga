"""Display helpers shared by the dashboard and a future GUI (no UI toolkit imports)."""


def _percentile(sorted_values, fraction):
    index = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[index]


class WaterfallScale:
    """Maps spectrum dB values onto 0..1 heatmap intensity.

    Auto (default) tracks each row's noise floor (a low percentile) and signal peak
    (a high percentile). Noise sits just above the bottom of the scale, so "noise"
    reads dim but distinct from "nothing", and signals saturate toward the top.
    The top expands quickly when a stronger signal appears and relaxes slowly, so
    bursts do not make the picture flicker. The span never shrinks below
    min_span_db, so a noise-only band is not stretched into false contrast.
    Manual mode uses fixed low/high limits and ignores updates.
    """

    def __init__(self, floor_percentile=0.2, peak_percentile=0.995, floor_margin_db=5.0,
                 headroom_db=3.0, min_span_db=30.0, attack=0.6, release=0.03, floor_rate=0.15):
        self.floor_percentile = floor_percentile
        self.peak_percentile = peak_percentile
        self.floor_margin_db = floor_margin_db
        self.headroom_db = headroom_db
        self.min_span_db = min_span_db
        self.attack = attack
        self.release = release
        self.floor_rate = floor_rate
        self.mode = 'auto'
        self.low = -120.0
        self.high = -120.0 + min_span_db
        self._initialized = False

    def set_manual(self, low_db, high_db):
        if not high_db > low_db:
            raise ValueError('manual scale needs high > low')
        self.mode, self.low, self.high = 'manual', float(low_db), float(high_db)

    def set_auto(self):
        self.mode = 'auto'
        self._initialized = False

    def update(self, row_db):
        """Feed one spectrum row in dB (e.g. protocol.power_db(fields))."""
        if self.mode != 'auto' or not row_db:
            return
        ordered = sorted(row_db)
        target_low = _percentile(ordered, self.floor_percentile) - self.floor_margin_db
        target_high = _percentile(ordered, self.peak_percentile) + self.headroom_db
        if not self._initialized:
            self.low, self.high = target_low, target_high
            self._initialized = True
        else:
            self.low += (target_low - self.low) * self.floor_rate
            rate = self.attack if target_high > self.high else self.release
            self.high += (target_high - self.high) * rate
        self.high = max(self.high, self.low + self.min_span_db)

    def normalize(self, value_db):
        """0.0 at or below low, 1.0 at or above high."""
        return min(1.0, max(0.0, (value_db - self.low) / (self.high - self.low)))
