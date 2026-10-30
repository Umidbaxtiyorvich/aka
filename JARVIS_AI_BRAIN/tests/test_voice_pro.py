"""Uzbek Voice AI: raqamlar, matnni tayyorlash, gapma-gap bo'lish, Azure TTS/STT (soxta server), zaxira va tuzatish."""
import json
import shutil

import pytest

from jarvis import net
from jarvis.voice_pro import VOICES, VoiceProError, normalize_for_speech, num_to_uz, split_sentences


def test_numbers_to_uzbek_words():
    assert num_to_uz(0) == "nol"
    assert num_to_uz(15) == "o'n besh"
    assert num_to_uz(2026) == "ikki ming yigirma olti"
    assert num_to_uz(1250000) == "bir million ikki yuz ellik ming"
    assert normalize_for_speech("Jami: 1 250 000 so'm 🎉 **muhim**") == "Jami: bir million ikki yuz ellik ming so'm muhim"
    assert "foiz" in normalize_for_speech("o'sish 12%")
    assert normalize_for_speech("1 250 000 so'm", numbers_to_words=False) == "1 250 000 so'm"


def test_split_long_answers():
    txt = "Bugungi savdo tayyor. " + "Mahsulot ro'yxati, " * 40 + "oxiri. Yana bir gap?"
    parts = split_sentences(txt)
    assert parts[0] == "Bugungi savdo tayyor." and all(len(p) <= 221 for p in parts) and parts[-1] == "Yana bir gap?"


def test_engine_selection_and_prepare(core, monkeypatch):
    assert core.voice_pro.tts_engine() in ("espeak", "browser")          # kalitsiz Azure tanlanmaydi
    monkeypatch.setenv("JARVIS_AZURE_SPEECH_KEY", "az-key-123456")
    core.settings.azure_speech_region = "westeurope"
    assert core.voice_pro.tts_engine() == "azure" and core.voice_pro.stt_engine() == "azure"
    p = core.voice_pro.prepare("Salom! Bugun 3 ta chek bo'ldi.")
    assert p["engine"] == "azure" and p["chunks"] == ["Salom!", "Bugun 3 ta chek bo'ldi."]   # Azure raqamni o'zi o'qiydi


def test_azure_tts_ssml_and_fallback(core, monkeypatch):
    monkeypatch.setenv("JARVIS_AZURE_SPEECH_KEY", "az-key-123456")
    core.settings.azure_speech_region = "westeurope"
    core.settings.voice_gender, core.settings.voice_rate, core.settings.voice_volume = "male", 10, 80
    seen = {}

    def ok(method, url, data, headers, timeout):
        seen.update(url=url, ssml=data.decode(), headers=headers)
        return 200, b"ID3fake-mp3", {}
    monkeypatch.setattr(net, "RAW_TRANSPORT", ok)
    audio, mime, eng = core.voice_pro.synth("Salom <do'stim> & mehmon")
    assert audio.startswith(b"ID3") and mime == "audio/mpeg" and VOICES["male"] in eng
    assert "westeurope.tts.speech.microsoft.com" in seen["url"] and "rate='+10%'" in seen["ssml"] and "volume='-20%'" in seen["ssml"]
    assert "&lt;do'stim&gt; &amp;" in seen["ssml"] and seen["headers"]["Ocp-Apim-Subscription-Key"] == "az-key-123456"
    monkeypatch.setattr(net, "RAW_TRANSPORT", lambda *a: (401, b"", {}))
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        audio, mime, eng = core.voice_pro.synth("Salom")
        assert eng.startswith("espeak") and mime == "audio/wav"             # Azure ishlamasa — mahalliy ovoz
    else:
        with pytest.raises(VoiceProError):
            core.voice_pro.synth("Salom")


def test_context_correction(core):
    fixed, fixes = core.voice_pro.correct("bugun mangomarket savdosi va qaymoqq narxi", ["Mango Market", "Qaymoq", "mangomarket"])
    assert fixes and fixes[0]["to"] in ("Qaymoq", "mangomarket")
    same, none = core.voice_pro.correct("salom dunyo", ["Mango Market"])
    assert same == "salom dunyo" and none == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg yo'q")
def test_azure_stt_mock(core, monkeypatch, tmp_path):
    import subprocess
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(wav)], check=True)
    monkeypatch.setenv("JARVIS_AZURE_SPEECH_KEY", "az-key-123456")
    core.settings.azure_speech_region = "westeurope"
    seen = {}

    def fake(method, url, data, headers, timeout):
        seen["url"], seen["ct"] = url, headers["Content-Type"]
        return 200, json.dumps({"RecognitionStatus": "Success", "DisplayText": "Bugun qancha savdo bo'ldi?",
                                "NBest": [{"Confidence": 0.91, "Display": "Bugun qancha savdo bo'ldi?"}]}).encode(), {}
    monkeypatch.setattr(net, "RAW_TRANSPORT", fake)
    r = core.voice_pro.transcribe(str(wav))
    assert r["text"] == "Bugun qancha savdo bo'ldi?" and r["engine"] == "azure" and r["confidence"] == 0.91
    assert "language=uz-UZ" in seen["url"] and "16000" in seen["ct"]


def test_voice_api(client, core):
    st = client.get("/api/voice/pro").json()
    assert "azure" in st["tts"] and st["tts"]["azure"]["ready"] is False and "Madina" in st["tts"]["azure"]["voices"]["female"]
    assert client.post("/api/voice/prepare", json={"text": "Bir. Ikki."}).json()["chunks"] == ["Bir.", "Ikki."]
    assert client.post("/api/settings", json={"voice_gender": "robot"}).status_code == 400
    assert client.post("/api/settings", json={"voice_rate": 90}).status_code == 400
    assert client.post("/api/settings", json={"voice_gender": "male", "voice_rate": -10, "azure_speech_region": "westeurope"}).status_code == 200
