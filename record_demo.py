import asyncio
import os
import shutil
import numpy as np
from scipy.io import wavfile
import static_ffmpeg
from playwright.async_api import async_playwright

static_ffmpeg.add_paths()

async def record_demo():
    print("🎬 Starting Playwright browser recording...")
    video_dir = "/config/Desktop/Session1/scratch_video"
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

        print("🌐 Navigating to live app at https://lifeflow-ai-258775721753.us-east4.run.app/...")
        await page.goto("https://lifeflow-ai-258775721753.us-east4.run.app/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Turn 1: Core app feature (Task Prioritization & Schedule)
        prompt1 = "I have 3 tasks due today: pay electricity bill ($120), buy groceries, and schedule dentist appointment. Can you prioritize these and give me a recommended schedule?"
        print(f"💬 Sending Turn 1: {prompt1}")
        
        await page.click("#input")
        for char in prompt1:
            await page.keyboard.press(char)
            await asyncio.sleep(0.008)
        
        await asyncio.sleep(0.3)
        await page.click("button[type='submit']")

        print("⏳ Waiting for Turn 1 response...")
        await page.wait_for_function(
            "() => { const bubbles = document.querySelectorAll('.msg.agent .bubble'); if (bubbles.length === 0) return false; const last = bubbles[bubbles.length - 1]; return last && !last.textContent.includes('Thinking'); }",
            timeout=45000
        )
        await asyncio.sleep(1.5)

        # Turn 2: Richer prompt with Tool Call & Calculation
        prompt2 = "Calculate my weekly bill total ($120 electricity + $85 groceries) and remaining budget from $300."
        print(f"💬 Sending Turn 2: {prompt2}")

        await page.click("#input")
        for char in prompt2:
            await page.keyboard.press(char)
            await asyncio.sleep(0.008)

        await asyncio.sleep(0.3)
        await page.click("button[type='submit']")

        print("⏳ Waiting for Turn 2 response...")
        await page.wait_for_function(
            "() => { const bubbles = document.querySelectorAll('.msg.agent .bubble'); if (bubbles.length < 2) return false; const last = bubbles[bubbles.length - 1]; return last && !last.textContent.includes('Thinking'); }",
            timeout=45000
        )
        await asyncio.sleep(1.5)

        # Turn 3: Generated Image prompt
        prompt3 = "Generate an achievement badge image for completing my task list today!"
        print(f"💬 Sending Turn 3: {prompt3}")

        await page.click("#input")
        for char in prompt3:
            await page.keyboard.press(char)
            await asyncio.sleep(0.008)

        await asyncio.sleep(0.3)
        await page.click("button[type='submit']")

        print("⏳ Waiting for Turn 3 response...")
        await page.wait_for_function(
            "() => { const bubbles = document.querySelectorAll('.msg.agent .bubble'); if (bubbles.length < 3) return false; const last = bubbles[bubbles.length - 1]; return last && !last.textContent.includes('Thinking'); }",
            timeout=45000
        )
        await asyncio.sleep(3.0)

        await context.close()
        await browser.close()

    files = [os.path.join(video_dir, f) for f in os.listdir(video_dir) if f.endswith(".webm")]
    if not files:
        raise RuntimeError("No recorded video file found!")
    raw_video_path = files[0]
    print(f"📹 Raw video recorded to: {raw_video_path}")
    return raw_video_path

def generate_lofi_music(duration_sec=35, sample_rate=44100):
    print("🎵 Generating upbeat lo-fi background music track...")
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
    chords = [
        [261.63, 329.63, 392.00, 493.88],  # Cmaj7
        [220.00, 261.63, 329.63, 392.00],  # Am7
        [293.66, 349.23, 440.00, 523.25],  # Dm7
        [196.00, 246.94, 293.66, 349.23],  # G7
    ]
    bpm = 75
    seconds_per_chord = 60 / bpm * 4
    audio = np.zeros_like(t)

    for i in range(len(t)):
        time_sec = t[i]
        chord_idx = int(time_sec // seconds_per_chord) % len(chords)
        chord_freqs = chords[chord_idx]
        chord_val = sum(np.sin(2 * np.pi * f * time_sec) * 0.15 for f in chord_freqs)
        bass_freq = chord_freqs[0] / 2
        bass_val = np.sin(2 * np.pi * bass_freq * time_sec) * 0.25
        beat_sec = (time_sec % (60 / bpm))
        kick = np.sin(2 * np.pi * 55 * beat_sec) * np.exp(-beat_sec * 15) if (int(time_sec * (bpm/60)) % 2 == 0) else 0
        snare = (np.random.uniform(-1, 1) * np.exp(-beat_sec * 25)) if (int(time_sec * (bpm/60)) % 2 == 1) else 0
        audio[i] = (chord_val + bass_val + kick * 0.4 + snare * 0.2)

    audio = audio / np.max(np.abs(audio)) * 0.8
    audio_int16 = (audio * 32767).astype(np.int16)

    wav_path = "/config/Desktop/Session1/lofi_music.wav"
    wavfile.write(wav_path, sample_rate, audio_int16)
    return wav_path

def merge_video_audio(video_path, audio_path, output_path):
    print("🎬 Merging recorded video with background music using ffmpeg (snappy 1.15x speedup)...")
    cmd = f'ffmpeg -y -i {video_path} -i {audio_path} -vf "setpts=0.87*PTS" -c:v libx264 -preset fast -crf 22 -c:a aac -shortest {output_path}'
    ret = os.system(cmd)
    if ret != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {ret}")
    print(f"✨ Final demo video produced: {output_path}")

def generate_gif(video_path, gif_path):
    print("🎞️ Generating optimized animated GIF...")
    cmd = f'ffmpeg -y -i {video_path} -vf "fps=10,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" {gif_path}'
    os.system(cmd)
    print(f"✨ Animated GIF produced: {gif_path}")

async def main():
    raw_vid = await record_demo()
    audio_wav = generate_lofi_music(duration_sec=35)
    
    mp4_path = "/config/Desktop/Session1/demo.mp4"
    gif_path = "/config/Desktop/Session1/demo.gif"
    lifeflow_mp4 = "/config/Desktop/Session1/lifeflow_demo_video.mp4"

    merge_video_audio(raw_vid, audio_wav, mp4_path)
    shutil.copyfile(mp4_path, lifeflow_mp4)
    generate_gif(mp4_path, gif_path)

if __name__ == "__main__":
    asyncio.run(main())
