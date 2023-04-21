# MIT License

# Copyright (c) 2023 David Rice

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
A.R.T.I.S.T. - Audio-Responsive Transformative Imagination Synthesis Technology

Generates images and verses of poetry based on user voice input.

Uses OpenAI's DALL-E 2 to generate images, GPT-3.5 Chat to generate verses
and Whisper API to transcribe speech.

Uses Azure Speech API to convert text to speech.

TODO: General cleanup and structural improvements

TODO: Improve logging to eliminate global logger object

TODO: Upload results to a site so users can download their creations
"""

import base64
import hashlib
import json
import logging
import random
import os
import string
import time
import wave

import pygame
import openai

from audio_tools import AudioPlayer, AudioRecorder
from azure_speech import AzureSpeech
from enum import IntEnum
from pygame.locals import *
from typing import Union


logger = logging.getLogger("ai-artist")


class Transcriber:
    def __init__(
        self, temp_dir: str, channels: int, sample_width: int, framerate: int
    ) -> None:
        self.temp_dir = temp_dir
        self.channels = channels
        self.sample_width = sample_width
        self.framerate = framerate

    def transcribe(self, audio_stream: bytes) -> str:
        """
        Transcribe audio stream to text.

        TODO: Find a way to do this in memory without temporary file
        """
        temp_file_name = os.path.join(self.temp_dir, "input_audio.wav")

        writer = wave.open(temp_file_name, "wb")

        writer.setnchannels(self.channels)
        writer.setsampwidth(self.sample_width)
        writer.setframerate(self.framerate)

        writer.writeframes(audio_stream)

        with open(temp_file_name, "rb") as f:
            try:
                response = openai.Audio.transcribe(model="whisper-1", file=f)
            except Exception as e:
                logger.error(f"Transcriber response: {response}")
                logger.exception(e)
                raise

        return response["text"]


class ChatResponse:
    def __init__(self, response: dict) -> None:
        self._response = response

    @property
    def content(self) -> str:
        return self._response["choices"][0]["message"]["content"]

    @property
    def total_tokens_used(self) -> int:
        return self._response["usage"]["total_tokens"]


class ChatCharacter:
    def __init__(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt
        self.reset()

    def reset(self) -> None:
        self._messages = [{"role": "system", "content": self._system_prompt}]

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, prompt: str) -> None:
        if self._messages[0]["role"] == "system":
            self._messages[0]["content"] = prompt
        else:
            raise RuntimeError("Invalid structure of ChatCharacter._messages")

    def get_chat_response(self, message: str) -> ChatResponse:
        self._messages.append({"role": "user", "content": message})

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo", messages=self._messages
        )

        self._messages.append(response["choices"][0]["message"])

        return ChatResponse(response)


def init_display(width: int, height: int) -> pygame.Surface:
    """
    Initialize pygame display.
    """
    pygame.init()

    pygame.mouse.set_visible(False)

    surface = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

    surface.fill(pygame.Color("black"))

    pygame.display.update()

    return surface


def init_joystick() -> Union[pygame.joystick.JoystickType, None]:
    """
    Initialize joystick if one is connected.

    Returns joystick object if one is connected, otherwise returns None.

    The returned joystick object must remain in scope for button press events
    to be detected.
    """
    pygame.joystick.init()

    if pygame.joystick.get_count() > 0:
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        return joystick
    else:
        return None


def speak_text(
    text: str, cache_dir: str, player: AudioPlayer, speech_svc: AzureSpeech
) -> None:
    """
    Speak text using Azure Speech API.
    Cache audio files to avoid unnecessary API calls.
    """
    logger.info(f"Speaking: {text}")
    text_details = speech_svc.language + speech_svc.gender + speech_svc.voice + text

    text_details_hash = hashlib.sha256(text_details.encode("utf-8")).hexdigest()

    logger.debug(f"Text details: {text_details} - Hash: {text_details_hash}")

    filename = os.path.join(cache_dir, f"{text_details_hash}.wav")

    if not os.path.exists(filename):
        logger.debug(f"Cache miss - generating audio file: {filename}")
        audio_data = speech_svc.text_to_speech(text)

        with wave.open(filename, "wb") as f:
            f.setnchannels(player.channels)
            f.setsampwidth(player.sample_width)
            f.setframerate(player.rate)
            f.writeframes(audio_data)

    with wave.open(filename, "rb") as f:
        logger.debug(f"Playing audio file: {filename}")
        player.play(f.readframes(f.getnframes()))


def check_for_event(
    js: Union[pygame.joystick.JoystickType, None],
    generate_button: int,
    daydream_button: int,
    shutdown_hold_button: int,
    shutdown_press_button: int,
) -> Union[str, None]:
    """
    Check for events and return a string representing the event if one is found.
    """
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN:
            if event.key == K_ESCAPE:
                return "Quit"
            if event.key == K_SPACE:
                return "Next"
            if event.key == K_d:
                return "Daydream"
        elif js and event.type == pygame.JOYBUTTONDOWN:
            if event.button == shutdown_press_button:
                if js.get_button(shutdown_hold_button):
                    return "Quit"
            if event.button == generate_button:
                return "Next"
            if event.button == daydream_button:
                return "Daydream"

    return None


def get_random_string(length: int) -> str:
    """
    Generate a random string of lowercase letters.

    Used for generating unique filenames.
    """
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def check_moderation(msg: str) -> bool:
    """
    Check if a message complies with content policy.

    Returns True if message is safe, False if it is not.
    """
    try:
        response = openai.Moderation.create(input=msg)
    except Exception as e:
        logger.error(f"Moderation response: {response}")
        logger.exception(e)
        raise

    flagged = response["results"][0]["flagged"]

    if flagged:
        logger.info(f"Message flagged by moderation: {msg}")
        logger.info(f"Moderation response: {response}")
    else:
        logger.info(f"Moderation check passed")

    return not flagged


def get_best_verse(
    poet: ChatCharacter,
    critic: ChatCharacter,
    base_prompt: str,
    user_prompt: str,
    num_verses: int,
) -> str:
    """
    Get num_verse verses from poet character, then use the critic character
    to choose the best verse.
    """

    # Poet and critic are both single-turn characters, so we reset them
    # before generating the verses.
    poet.reset()
    critic.reset()

    verses: list[str] = []

    for _ in range(num_verses):
        # Generate a verse
        try:
            verse = poet.get_chat_response(base_prompt + " " + user_prompt).content
        except Exception as e:
            logger.error(f"Error getting verse from poet")
            logger.exception(e)
            raise

        verses.append(verse)

    critic_message = f"Theme: {user_prompt}\n"

    for verse in enumerate(verses, start=1):
        critic_message += f"Poem {verse[0]}: {verse[1]}\n"

    critic_log_message = critic_message.strip().replace("\n", "/")
    logger.info(f"Critic message: {critic_log_message}")

    chosen_poem = None

    try:
        critic_verdict = critic.get_chat_response(critic_message).content
        logger.info(f"Critic verdict: {critic_verdict}")

        for c in critic_verdict:
            if c.isdigit():
                chosen_poem = int(c)
                logger.debug(f"Chosen poem number: {chosen_poem}")
                break
    except Exception as e:
        logger.error(f"Error getting verdict from critic")
        logger.exception(e)
        raise

    if chosen_poem is not None:  # Maybe there could be an index 0 someday?
        return verses[chosen_poem - 1]
    else:
        logger.warning(
            f"No poem number found in critic verdict - returning random verse"
        )
        return random.choice(verses)


def show_status_screen(
    surface: pygame.Surface, text: str, horiz_margin: int, vert_margin: int
) -> None:
    """
    Show a status screen with a message.

    TODO: Generalize positioning code and remove magic numbers
    """
    surface.fill(pygame.Color("black"))

    font = pygame.font.SysFont("Arial", 200)
    x_pos = int(surface.get_width() / 2 - font.size("A.R.T.I.S.T.")[0] / 2)
    text_surface = font.render("A.R.T.I.S.T.", True, pygame.Color("white"))
    surface.blit(text_surface, (x_pos, vert_margin))

    font = pygame.font.SysFont("Arial", 60)
    tagline = "Audio-Responsive Transformative Imagination Synthesis Technology"
    x_pos = int(surface.get_width() / 2 - font.size(tagline)[0] / 2)
    text_surface = font.render(tagline, True, pygame.Color("white"))
    surface.blit(text_surface, (x_pos, 250))

    font = pygame.font.SysFont("Arial", 100)
    x_pos = int(surface.get_width() / 2 - font.size(text)[0] / 2)
    text_surface = font.render(text, True, pygame.Color("white"))
    surface.blit(text_surface, (x_pos, 500))

    pygame.display.update()


def main() -> None:
    try:
        openai.api_key = os.environ["OPENAI_API_KEY"]
        azure_speech_region = os.environ["AZURE_SPEECH_REGION"]
        azure_speech_key = os.environ["AZURE_SPEECH_KEY"]
    except KeyError:
        print("Please set environment variables for OpenAI and Azure Speech.")
        return

    try:
        with open("config.json", "r") as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        print("Please create a config.json file.")
        return

    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler("artist.log")
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)-8s - %(message)s"
    )

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("*** Starting A.R.T.I.S.T. ***")

    cache_dir = config["speech_cache_dir"]
    transcribe_temp_dir = config["transcribe_temp_dir"]
    output_dir = config["output_dir"]

    language = config["speech_language"]
    gender = config["speech_gender"]
    voice = config["speech_voice"]
    input_sample_rate = config["input_sample_rate"]
    output_sample_rate = config["output_sample_rate"]

    max_recording_time = config["max_recording_time"]

    img_width = config["img_width"]
    img_height = config["img_height"]

    img_size = f"{img_width}x{img_height}"

    display_width = config["display_width"]
    display_height = config["display_height"]

    horiz_margin = config["horiz_margin"]
    vert_margin = config["vert_margin"]

    generate_button = config["generate_button"]
    daydream_button = config["daydream_button"]
    shutdown_hold_button = config["shutdown_hold_button"]
    shutdown_press_button = config["shutdown_press_button"]

    image_base_prompt = config["image_base_prompt"]

    num_verses = config["num_verses"]

    min_daydream_time = config["min_daydream_time"] * 60  # Convert to seconds
    max_daydream_time = config["max_daydream_time"] * 60  # Convert to seconds

    max_consecutive_daydreams = config["max_consecutive_daydreams"]

    artist_system_prompt = config["artist_system_prompt"]
    artist_base_prompt = config["artist_base_prompt"]
    poet_system_prompt = config["poet_system_prompt"]
    verse_base_prompt = config["verse_base_prompt"]
    critic_system_prompt = config["critic_system_prompt"]

    verse_font = config["verse_font"]
    verse_font_size = config["verse_font_size"]
    verse_line_spacing = config["verse_line_spacing"]

    max_verse_width = (display_width - img_width) - (horiz_margin * 3)

    random.seed()

    logger.debug("Initializing display...")
    disp_surface = init_display(width=display_width, height=display_height)

    logger.debug("Initializing joystick...")
    js = init_joystick()

    logger.debug("Initializing speech...")
    speech_svc = AzureSpeech(
        subscription_key=azure_speech_key,
        region=azure_speech_region,
        language=language,
        gender=gender,
        voice=voice,
    )

    logger.debug("Initializing audio player...")
    audio_player = AudioPlayer(sample_width=2, channels=1, rate=output_sample_rate)

    logger.debug("Initializing audio recorder...")
    audio_recorder = AudioRecorder(sample_width=2, channels=1, rate=input_sample_rate)

    logger.debug("Initializing transcriber...")
    transcriber = Transcriber(
        temp_dir=transcribe_temp_dir,
        channels=1,
        sample_width=2,
        framerate=input_sample_rate,
    )

    logger.debug("Initialzing autonomous AI artist...")
    ai_artist = ChatCharacter(system_prompt=artist_system_prompt)

    logger.debug("Initializing poet...")
    poet = ChatCharacter(system_prompt=poet_system_prompt)

    logger.debug("Initializing critic...")
    critic = ChatCharacter(system_prompt=critic_system_prompt)

    start_new = True
    daydream = False

    consecutive_daydreams = 0

    msg = ""

    show_status_screen(
        surface=disp_surface,
        text="Ready",
        horiz_margin=horiz_margin,
        vert_margin=vert_margin,
    )

    next_change_time = time.monotonic() + random.randint(
        min_daydream_time, max_daydream_time
    )

    while True:
        while True:
            status = check_for_event(
                js=js,
                generate_button=generate_button,
                daydream_button=daydream_button,
                shutdown_hold_button=shutdown_hold_button,
                shutdown_press_button=shutdown_press_button,
            )

            # TODO: More cleanup
            if time.monotonic() >= next_change_time:
                status = "Daydream"

            if status == "Quit":
                logger.info("*** A.R.T.I.S.T. is shutting down. ***")
                pygame.quit()
                return
            elif status == "Next":
                start_new = True
                daydream = False
                consecutive_daydreams = 0
                break
            elif status == "Daydream":
                start_new = True
                daydream = True
                consecutive_daydreams += 1
                break

        # TODO: Major cleanup of the way daydreaming works. This is currently very messy.

        if start_new:
            if consecutive_daydreams > max_consecutive_daydreams:
                logger.info("Daydream limit reached")

                next_change_time = time.monotonic() + random.randint(
                    min_daydream_time, max_daydream_time
                )
                continue
            if not daydream:
                logger.info("=== Starting new creation ===")

                show_status_screen(
                    surface=disp_surface,
                    text=" ",
                    horiz_margin=horiz_margin,
                    vert_margin=vert_margin,
                )
                pygame.display.update()

                greeting_phrase = (
                    random.choice(config["welcome_words"])
                    + " "
                    + random.choice(config["welcome_lines"])
                )

                speak_text(
                    text=greeting_phrase,
                    cache_dir=cache_dir,
                    player=audio_player,
                    speech_svc=speech_svc,
                )

                show_status_screen(
                    surface=disp_surface,
                    text="Listening...",
                    horiz_margin=horiz_margin,
                    vert_margin=vert_margin,
                )

                logger.debug("Recording...")
            else:
                logger.info("=== Starting daydream ===")

            start_new = False

        silent_loops = 0

        while silent_loops < 10:
            if not daydream:
                (in_stream, valid_audio) = audio_recorder.record(max_recording_time)
            else:
                valid_audio = True  # Messy, clean this up

            if valid_audio:
                if not daydream:
                    show_status_screen(
                        surface=disp_surface,
                        text="Working...",
                        horiz_margin=horiz_margin,
                        vert_margin=vert_margin,
                    )
                    working_phrase = random.choice(config["working_lines"])

                    speak_text(
                        text=working_phrase,
                        cache_dir=cache_dir,
                        player=audio_player,
                        speech_svc=speech_svc,
                    )

                    msg = transcriber.transcribe(audio_stream=in_stream)

                    logger.info(f"Transcribed: {msg}")
                else:
                    show_status_screen(
                        surface=disp_surface,
                        text="Daydreaming...",
                        horiz_margin=horiz_margin,
                        vert_margin=vert_margin,
                    )

                    if msg:
                        msg = ai_artist.get_chat_response(
                            message=artist_base_prompt + " " + msg
                        ).content
                    else:
                        msg = ai_artist.get_chat_response(
                            message=artist_base_prompt + " something completely random."
                        ).content

                    logger.info(f"Daydreamed: {msg}")

                name = get_random_string(12)

                logger.info(f"Base name: {name}")

                with open(os.path.join(output_dir, name + ".txt"), "w") as f:
                    f.write(msg)

                img_prompt = image_base_prompt + msg

                can_create = check_moderation(img_prompt)
                creation_failed = False
                response = None  # Clear out previous response

                if can_create:
                    try:
                        response = openai.Image.create(
                            prompt=img_prompt, size=img_size, response_format="b64_json"
                        )
                    except Exception as e:
                        logger.error(f"Image creation response: {response}")
                        logger.exception(e)
                        creation_failed = True

                    if not creation_failed:
                        img_bytes = base64.b64decode(response["data"][0]["b64_json"])

                        logger.debug("Getting best verse...")
                        verse = get_best_verse(
                            poet=poet,
                            critic=critic,
                            base_prompt=verse_base_prompt,
                            user_prompt=msg,
                            num_verses=num_verses,
                        )

                        verse_lines = verse.split("\n")

                        verse_lines = [line.strip() for line in verse_lines]
                        logger.info(f"Verse: {'/'.join(verse_lines)}")

                        font_obj = pygame.font.SysFont(verse_font, verse_font_size)
                        longest_size = 0

                        # Need to check pizel size of each line to account for
                        # proprtional fonts. Assumes that size scales linearly.
                        for line in verse_lines:
                            text_size = font_obj.size(line)
                            if text_size[0] > longest_size:
                                longest_size = text_size[0]
                                longest_line = line

                        font_size = verse_font_size
                        will_fit = False

                        while not will_fit:
                            font_obj = pygame.font.SysFont(verse_font, font_size)

                            text_size = font_obj.size(longest_line)

                            if text_size[0] < max_verse_width:
                                will_fit = True
                            else:
                                font_size -= 2

                        total_height = 0

                        for line in verse_lines:
                            text_size = font_obj.size(line)

                            total_height += text_size[1]
                            total_height += verse_line_spacing

                        total_height -= verse_line_spacing  # No spacing after last line

                        offset = -int(total_height / 2)

                        img_side = random.choice(["left", "right"])

                        disp_surface.fill(pygame.Color("black"))

                        if img_side == "left":
                            img_x = horiz_margin
                            verse_x = horiz_margin + img_width + horiz_margin
                        else:
                            img_x = display_width - horiz_margin - img_width
                            verse_x = horiz_margin

                        for line in verse_lines:
                            text_surface_obj = font_obj.render(
                                line, True, pygame.Color("white")
                            )
                            disp_surface.blit(
                                text_surface_obj,
                                (verse_x, int((display_height / 2) + offset)),
                            )
                            offset += int(total_height / len(verse_lines))

                        finished_phrase = random.choice(config["finished_lines"])

                        if not daydream:
                            speak_text(
                                text=finished_phrase,
                                cache_dir=cache_dir,
                                player=audio_player,
                                speech_svc=speech_svc,
                            )

                        logger.debug("Saving image...")
                        with open(os.path.join(output_dir, name + ".png"), "wb") as f:
                            f.write(img_bytes)

                        img = pygame.image.load(os.path.join(output_dir, name + ".png"))
                        disp_surface.blit(img, (img_x, vert_margin))
                        pygame.display.update()

                        logger.debug("Saving screenshot...")
                        pygame.image.save(
                            disp_surface, os.path.join(output_dir, name + "-verse.png")
                        )

                        next_change_time = time.monotonic() + random.randint(
                            min_daydream_time, max_daydream_time
                        )
                    else:
                        show_status_screen(
                            surface=disp_surface,
                            text="Creation failed!",
                            horiz_margin=horiz_margin,
                            vert_margin=vert_margin,
                        )
                        failed_phrase = random.choice(config["failed_lines"])

                        speak_text(
                            text=failed_phrase,
                            cache_dir=cache_dir,
                            player=audio_player,
                            speech_svc=speech_svc,
                        )
                else:
                    show_status_screen(
                        surface=disp_surface,
                        text="Creation failed!",
                        horiz_margin=horiz_margin,
                        vert_margin=vert_margin,
                    )
                    failed_phrase = random.choice(config["failed_lines"])

                    speak_text(
                        text=failed_phrase,
                        cache_dir=cache_dir,
                        player=audio_player,
                        speech_svc=speech_svc,
                    )

                break
            else:
                silent_loops += 1

        if silent_loops == 10:
            logger.debug("Silence detected")
            show_status_screen(
                surface=disp_surface,
                text="Ready",
                horiz_margin=horiz_margin,
                vert_margin=vert_margin,
            )


if __name__ == "__main__":
    main()
