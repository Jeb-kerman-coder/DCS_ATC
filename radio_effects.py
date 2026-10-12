import numpy as np
from scipy.signal import butter, sosfilt


class RadioEffects:
    """
    profile "radio":    heavy UHF/VHF radio (ATC, AWACS)
    profile "intercom": the wingman - same radio, but a cleaner, wider
                        signal with far less static, so the two voices
                        are easy to tell apart.
    """

    PROFILES = {
        "radio": dict(
            highpass_hz=300, lowpass_hz=3400, distortion_amount=2.0,
            static_level=0.025, crackle_level=0.035,
            burst_duration=0.10, burst_level=0.18
        ),
        "intercom": dict(
            highpass_hz=200, lowpass_hz=4200, distortion_amount=1.4,
            static_level=0.008, crackle_level=0.010,
            burst_duration=0.06, burst_level=0.08
        ),
    }

    def __init__(self, profile="radio"):

        for key, value in self.PROFILES.get(
            profile, self.PROFILES["radio"]
        ).items():
            setattr(self, key, value)

    def _filter(self, audio, sample_rate, cutoff, filter_type):
        sos = butter(
            4,
            cutoff,
            btype=filter_type,
            fs=sample_rate,
            output="sos"
        )

        return sosfilt(sos, audio)

    def generate_static_burst(self, sample_rate, duration=None):
        if duration is None:
            duration = self.burst_duration

        samples = int(sample_rate * duration)

        noise = np.random.normal(
            0,
            self.burst_level,
            samples
        ).astype(np.float32)

        # Give the burst the same radio bandwidth
        noise = self._filter(
            noise,
            sample_rate,
            self.highpass_hz,
            "highpass"
        )

        noise = self._filter(
            noise,
            sample_rate,
            self.lowpass_hz,
            "lowpass"
        )

        # Fade in/out so it sounds like a radio burst
        fade_samples = max(
            1,
            int(sample_rate * 0.015)
        )

        fade_in = np.linspace(
            0,
            1,
            fade_samples
        )

        fade_out = np.linspace(
            1,
            0,
            fade_samples
        )

        noise[:fade_samples] *= fade_in
        noise[-fade_samples:] *= fade_out

        return noise.astype(np.float32)

    def process(self, audio, sample_rate):
        audio = np.asarray(
            audio,
            dtype=np.float32
        )

        if audio.ndim > 1:
            audio = np.mean(
                audio,
                axis=1
            )

        # Radio bandwidth
        audio = self._filter(
            audio,
            sample_rate,
            self.highpass_hz,
            "highpass"
        )

        audio = self._filter(
            audio,
            sample_rate,
            self.lowpass_hz,
            "lowpass"
        )

        # Distortion
        audio = np.tanh(
            audio * self.distortion_amount
        )

        # Background static
        noise = np.random.normal(
            0,
            self.static_level,
            len(audio)
        ).astype(np.float32)

        noise = self._filter(
            noise,
            sample_rate,
            self.highpass_hz,
            "highpass"
        )

        noise = self._filter(
            noise,
            sample_rate,
            self.lowpass_hz,
            "lowpass"
        )

        # Occasional crackle
        crackle = np.random.normal(
            0,
            self.crackle_level,
            len(audio)
        ).astype(np.float32)

        crackle_mask = (
            np.random.random(len(audio)) < 0.002
        )

        crackle *= crackle_mask

        audio = (
            audio +
            noise +
            crackle
        )

        peak = np.max(
            np.abs(audio)
        )

        if peak > 0:
            audio = audio / peak

        audio *= 0.85

        return audio.astype(np.float32)

    def create_transmission(self, audio, sample_rate):
        # Process the voice first
        audio = self.process(
            audio,
            sample_rate
        )

        # Static before transmission
        start_burst = self.generate_static_burst(
            sample_rate
        )

        # Static after transmission
        end_burst = self.generate_static_burst(
            sample_rate
        )

        # Complete radio transmission
        transmission = np.concatenate([
            start_burst,
            audio,
            end_burst
        ])

        return transmission.astype(np.float32)