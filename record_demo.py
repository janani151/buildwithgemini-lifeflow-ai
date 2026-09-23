import asyncio
import os
import shutil
import base64
import numpy as np
from scipy.io import wavfile
import static_ffmpeg
from playwright.async_api import async_playwright

static_ffmpeg.add_paths()

async def record_demo():
    print("🎬 Starting Playwright browser recording...")
    video_dir = "/config/Desktop/Session1/life-organizer-assistant/scratch_video"
    if os.path.exists(video_dir):
        shutil.rmtree(video_dir)
    os.makedirs(video_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=video_dir,
            record_video_size={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        print("🌐 Navigating to https://lifeflow-ai-851623494397.us-east1.run.app...")
        await page.goto("https://lifeflow-ai-851623494397.us-east1.run.app/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Turn 1: Core app feature (Task Prioritization & Schedule)
        prompt1 = "I have 3 tasks due today: pay electricity bill ($120), buy groceries, and schedule dentist appointment. Can you prioritize these and give me a recommended schedule?"
        print(f"💬 Sending Turn 1: {prompt1}")
        
        # Type character by character for smooth video demonstration effect
        await page.click("#input")
        for char in prompt1:
            await page.keyboard.press(char)
            await asyncio.sleep(0.02)
        
        await asyncio.sleep(0.5)
        await page.click("button[type='submit']")

        # Wait for agent response bubble & card
        print("⏳ Waiting for Turn 1 response...")
        await page.wait_for_selector(".msg.agent .bubble", timeout=30000)
        await asyncio.sleep(8)  # Hold view on screen to display response & cards

        # Turn 2: Richer prompt with Tool Call & Generated Image
        prompt2 = "Generate a motivational goal achievement badge image for completing my morning routine, and calculate my weekly bill total ($120 electricity + $85 groceries) and remaining budget from $300."
        print(f"💬 Sending Turn 2: {prompt2}")

        await page.click("#input")
        for char in prompt2:
            await page.keyboard.press(char)
            await asyncio.sleep(0.02)

        await asyncio.sleep(0.5)
        await page.click("button[type='submit']")

        # Wait for agent response & image card
        print("⏳ Waiting for Turn 2 response & generated image...")
        await page.wait_for_selector(".msg.agent .bubble img, .msg.agent .bubble .a2card", timeout=45000)
        await asyncio.sleep(10)  # Hold final screen to showcase generated image and calculations

        await context.close()
        await browser.close()

    # Find recorded video file
    files = [os.path.join(video_dir, f) for f in os.listdir(video_dir) if f.endswith(".webm")]
    if not files:
        raise RuntimeError("No recorded video file found!")
    raw_video_path = files[0]
    print(f"📹 Raw video recorded to: {raw_video_path}")
    return raw_video_path

def generate_lofi_music(duration_sec=30, sample_rate=44100):
    """Generates a pleasant, chill, upbeat lo-fi synth chord progression audio track using numpy."""
    print("🎵 Generating upbeat lo-fi background music track...")
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
    
    # Lo-fi chord frequencies (Maj7 & Min7 chords: Cmaj7, Am7, Dm7, G7)
    chords = [
        [261.63, 329.63, 392.00, 493.88],  # Cmaj7
        [220.00, 261.63, 329.63, 392.00],  # Am7
        [293.66, 349.23, 440.00, 523.25],  # Dm7
        [196.00, 246.94, 293.66, 349.23],  # G7
    ]

    bpm = 75
    seconds_per_chord = 60 / bpm * 4  # 3.2s per chord measure
    
    audio = np.zeros_like(t)

    # Synthesis loop
    for i in range(len(t)):
        time_sec = t[i]
        chord_idx = int(time_sec // seconds_per_chord) % len(chords)
        chord_freqs = chords[chord_idx]
        
        # Soft sine waves for warm vinyl synth feel
        chord_val = sum(np.sin(2 * np.pi * f * time_sec) * 0.15 for f in chord_freqs)
        
        # Sub bass line
        bass_freq = chord_freqs[0] / 2
        bass_val = np.sin(2 * np.pi * bass_freq * time_sec) * 0.25
        
        # Chill lo-fi kick & snare rhythm (kick on 1 & 3, snare on 2 & 4)
        beat_sec = (time_sec % (60 / bpm))
        kick = np.sin(2 * np.pi * 55 * beat_sec) * np.exp(-beat_sec * 15) if (int(time_sec * (bpm/60)) % 2 == 0) else 0
        snare = (np.random.uniform(-1, 1) * np.exp(-beat_sec * 25)) if (int(time_sec * (bpm/60)) % 2 == 1) else 0

        audio[i] = (chord_val + bass_val + kick * 0.4 + snare * 0.2)

    # Normalize audio
    audio = audio / np.max(np.abs(audio)) * 0.8
    audio_int16 = (audio * 32767).astype(np.int16)

    wav_path = "/config/Desktop/Session1/life-organizer-assistant/lofi_music.wav"
    wavfile.write(wav_path, sample_rate, audio_int16)
    print(f"🎶 Lo-fi background music saved to: {wav_path}")
    return wav_path

def merge_video_audio(video_path, audio_path, output_path):
    print("🎬 Merging recorded video with lo-fi background music using ffmpeg...")
    cmd = f"ffmpeg -y -i {video_path} -i {audio_path} -c:v libx264 -preset fast -crf 22 -c:a aac -shortest {output_path}"
    ret = os.system(cmd)
    if ret != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {ret}")
    print(f"✨ Final demo video produced: {output_path}")

async def main():
    raw_vid = await record_demo()
    
    # Check video duration using ffprobe / estimate ~30s
    audio_wav = generate_lofi_music(duration_sec=40)
    
    output_mp4 = "/config/Desktop/Session1/life-organizer-assistant/lifeflow_demo_video.mp4"
    merge_video_audio(raw_vid, audio_wav, output_mp4)

if __name__ == "__main__":
    asyncio.run(main())
