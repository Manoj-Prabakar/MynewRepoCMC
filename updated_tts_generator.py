"""
Optimized TTS -> STT pipeline.
Generates temporary MP3 files, immediately transcribes them,
appends transcripts to CSV, deletes audio instantly, and exports Excel once at the end.

This version keeps the original multi-TTS support (Edge / Google / Azure)
but removes the old MP3 -> WAV / Dialogflow-ready storage path.
"""

import asyncio
import concurrent.futures
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import edge_tts

# Try to import Google Cloud TTS
try:
    from google.cloud import texttospeech
    GOOGLE_TTS_AVAILABLE = True
except ImportError:
    GOOGLE_TTS_AVAILABLE = False
    print("[WARNING] google-cloud-texttospeech not installed. Google TTS will not be available.")

# Try to import Azure TTS
try:
    import azure.cognitiveservices.speech as speechsdk
    AZURE_TTS_AVAILABLE = True
except ImportError:
    AZURE_TTS_AVAILABLE = False
    print("[WARNING] azure-cognitiveservices-speech not installed. Azure TTS will not be available.")

# Simple STT using Whisper
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("[WARNING] openai-whisper not installed. STT will not be available.")

ACCENTS = [
    'indian_english',
    'french_english',
    'chinese_english',
    'spanish_english',
    'australian_english',
    'regular_english'
]

GENDERS = ['male', 'female']

CSV_HEADERS = [
    'utterance_id',
    'input_text',
    'accent',
    'gender',
    'voice',
    'stt_text',
    'status'
]


async def discover_voices_edge():
    """Discover available Edge TTS voices and map them to our accent/gender requirements."""
    print("=" * 60)
    print("🔍 Discovering available Edge TTS voices...")
    print("=" * 60)

    print("  Connecting to Edge TTS service...", end=" ", flush=True)
    voices = await edge_tts.list_voices()
    print(f"✓ Found {len(voices)} total voices")

    voice_mapping = {
        'indian_english': {'male': None, 'female': None},
        'french_english': {'male': None, 'female': None},
        'chinese_english': {'male': None, 'female': None},
        'spanish_english': {'male': None, 'female': None},
        'australian_english': {'male': None, 'female': None},
        'regular_english': {'male': None, 'female': None}
    }

    english_voices = [v for v in voices if v['Locale'].startswith('en')]
    spanish_voices = [v for v in voices if 'es-' in v['Locale'].lower()]
    french_voices = [v for v in voices if 'fr-' in v['Locale'].lower()]
    chinese_voices = [v for v in voices if 'zh-' in v['Locale'].lower() or 'cn-' in v['Locale'].lower()]

    accent_locale_map = {
        'indian_english': {'search_in': 'english', 'locales': ['en-IN']},
        'french_english': {'search_in': 'both', 'locales': ['en-FR', 'fr-FR', 'fr-CA']},
        'chinese_english': {'search_in': 'both', 'locales': ['en-CN', 'zh-CN', 'zh-HK']},
        'spanish_english': {'search_in': 'both', 'locales': ['es-US', 'es-MX', 'en-ES', 'es-ES']},
        'australian_english': {'search_in': 'english', 'locales': ['en-AU', 'en-GB']},
        'regular_english': {'search_in': 'english', 'locales': ['en-US', 'en-GB', 'en-AU', 'en-CA']}
    }

    used_voices = set()

    print("\n  🔗 Mapping voices to accents...")
    for accent_key in voice_mapping.keys():
        accent_config = accent_locale_map.get(accent_key, {'search_in': 'english', 'locales': ['en-US']})
        target_locales = accent_config['locales']
        search_in = accent_config['search_in']

        if search_in == 'english':
            voice_list = english_voices
        elif search_in == 'both':
            if accent_key == 'spanish_english':
                voice_list = english_voices + spanish_voices
            elif accent_key == 'french_english':
                voice_list = english_voices + french_voices
            elif accent_key == 'chinese_english':
                voice_list = english_voices + chinese_voices
            else:
                voice_list = english_voices
        else:
            voice_list = english_voices

        for gender in ['Male', 'Female']:
            selected_voice = None
            for target_locale in target_locales:
                matching_voices = [
                    v for v in voice_list
                    if v['Gender'] == gender and target_locale in v['Locale'] and v['ShortName'] not in used_voices
                ]
                if accent_key == 'spanish_english' and matching_voices:
                    multilingual = [v for v in matching_voices if 'Multilingual' in v.get('ShortName', '')]
                    if multilingual:
                        matching_voices = multilingual
                if matching_voices:
                    selected_voice = matching_voices[0]
                    break

            if not selected_voice:
                fallback_voices = [
                    v for v in english_voices
                    if v['Gender'] == gender and v['ShortName'] not in used_voices
                ]
                if fallback_voices:
                    selected_voice = fallback_voices[0]

            if selected_voice:
                voice_mapping[accent_key][gender.lower()] = selected_voice['ShortName']
                used_voices.add(selected_voice['ShortName'])
                print(
                    f"    ✓ {accent_key:20s} {gender.lower():6s} -> "
                    f"{selected_voice['ShortName']:30s} ({selected_voice['Locale']})"
                )

    return voice_mapping


def discover_voices_google(creds_path=None):
    """Discover available Google TTS voices and map them to our accent/gender requirements."""
    if not GOOGLE_TTS_AVAILABLE:
        raise ImportError("google-cloud-texttospeech is not installed. Install it with: pip install google-cloud-texttospeech")

    print("=" * 60)
    print("🔍 Discovering available Google TTS voices...")
    print("=" * 60)

    if creds_path:
        from google.oauth2 import service_account
        creds_path = Path(creds_path)
        if not creds_path.exists():
            raise FileNotFoundError(f"Service account key file not found: {creds_path}")
        credentials = service_account.Credentials.from_service_account_file(str(creds_path))
    else:
        credentials = None

    if credentials:
        client = texttospeech.TextToSpeechClient(credentials=credentials)
    else:
        client = texttospeech.TextToSpeechClient()

    voices = client.list_voices()

    voice_mapping = {
        'indian_english': {'male': None, 'female': None},
        'french_english': {'male': None, 'female': None},
        'chinese_english': {'male': None, 'female': None},
        'spanish_english': {'male': None, 'female': None},
        'australian_english': {'male': None, 'female': None},
        'regular_english': {'male': None, 'female': None}
    }

    accent_language_map = {
        'indian_english': ['en-IN'],
        'french_english': ['en-GB', 'fr-FR'],
        'chinese_english': ['en-GB', 'zh-CN'],
        'spanish_english': ['en-US', 'es-ES', 'es-US'],
        'australian_english': ['en-AU', 'en-GB', 'en-US'],
        'regular_english': ['en-US', 'en-GB', 'en-AU', 'en-CA']
    }

    gender_map = {
        'male': texttospeech.SsmlVoiceGender.MALE,
        'female': texttospeech.SsmlVoiceGender.FEMALE
    }

    english_voices = [v for v in voices.voices if v.language_codes and any(lc.startswith('en') for lc in v.language_codes)]
    used_voices = set()

    for accent_key in voice_mapping.keys():
        target_languages = accent_language_map.get(accent_key, ['en-US'])
        for gender_key, gender_enum in gender_map.items():
            selected_voice = None
            for target_lang in target_languages:
                matching_voices = [
                    v for v in voices.voices
                    if v.ssml_gender == gender_enum
                    and v.language_codes
                    and (target_lang in v.language_codes or any(lc.startswith(target_lang.split('-')[0]) for lc in v.language_codes))
                    and v.name not in used_voices
                ]
                if matching_voices:
                    exact_match = [v for v in matching_voices if target_lang in v.language_codes]
                    selected_voice = exact_match[0] if exact_match else matching_voices[0]
                    break

            if not selected_voice:
                fallback_voices = [
                    v for v in english_voices
                    if v.ssml_gender == gender_enum and v.name not in used_voices
                ]
                if fallback_voices:
                    selected_voice = fallback_voices[0]

            if selected_voice:
                voice_mapping[accent_key][gender_key] = selected_voice.name
                used_voices.add(selected_voice.name)

    return voice_mapping


def discover_voices_azure(azure_key=None, azure_region=None):
    """Discover available Azure TTS voices and map them to our accent/gender requirements."""
    if not AZURE_TTS_AVAILABLE:
        raise ImportError("azure-cognitiveservices-speech is not installed. Install it with: pip install azure-cognitiveservices-speech")
    if not azure_key or not azure_region:
        raise ValueError("Azure TTS requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")

    import requests

    url = f"https://{azure_region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
    headers = {"Ocp-Apim-Subscription-Key": azure_key}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    voices_data = response.json()

    voice_mapping = {
        'indian_english': {'male': None, 'female': None},
        'french_english': {'male': None, 'female': None},
        'chinese_english': {'male': None, 'female': None},
        'spanish_english': {'male': None, 'female': None},
        'australian_english': {'male': None, 'female': None},
        'regular_english': {'male': None, 'female': None}
    }

    accent_language_map = {
        'indian_english': ['en-IN'],
        'french_english': ['fr-FR', 'fr-CA', 'en-GB'],
        'chinese_english': ['zh-CN', 'zh-HK', 'en-GB'],
        'spanish_english': ['es-ES', 'es-MX', 'es-US', 'en-US'],
        'australian_english': ['en-AU', 'en-GB', 'en-US'],
        'regular_english': ['en-US', 'en-GB', 'en-AU', 'en-CA']
    }

    gender_map = {'male': 'Male', 'female': 'Female'}
    english_voices = [v for v in voices_data if v.get('Locale', '').startswith('en')]
    used_voices = set()

    for accent_key in voice_mapping.keys():
        target_languages = accent_language_map.get(accent_key, ['en-US'])
        for gender_key, gender_value in gender_map.items():
            selected_voice = None
            for target_lang in target_languages:
                exact_match = [
                    v for v in voices_data
                    if v.get('Gender', '').lower() == gender_value.lower()
                    and v.get('Locale', '') == target_lang
                    and v.get('ShortName') not in used_voices
                ]
                if exact_match:
                    selected_voice = exact_match[0]
                    break

                lang_prefix = target_lang.split('-')[0]
                prefix_match = [
                    v for v in voices_data
                    if v.get('Gender', '').lower() == gender_value.lower()
                    and v.get('Locale', '').startswith(lang_prefix + '-')
                    and v.get('ShortName') not in used_voices
                ]
                if prefix_match:
                    selected_voice = prefix_match[0]
                    break

            if not selected_voice:
                fallback_voices = [
                    v for v in english_voices
                    if v.get('Gender', '').lower() == gender_value.lower()
                    and v.get('ShortName') not in used_voices
                ]
                if fallback_voices:
                    selected_voice = fallback_voices[0]

            if selected_voice:
                voice_name = selected_voice.get('ShortName', '')
                voice_mapping[accent_key][gender_key] = voice_name
                used_voices.add(voice_name)

    return voice_mapping


async def discover_voices(tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    tts_service = tts_service.lower()
    if tts_service == 'google':
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, discover_voices_google, creds_path)
    if tts_service == 'azure':
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, discover_voices_azure, azure_key, azure_region)
    return await discover_voices_edge()


async def generate_audio_edge(text, voice_name, output_path):
    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(str(output_path))
        return Path(output_path).exists()
    except Exception as e:
        print(f"[ERROR] Edge TTS generation failed for {output_path}: {e}")
        return False


def generate_audio_google(text, voice_name, output_path, creds_path=None):
    if not GOOGLE_TTS_AVAILABLE:
        raise ImportError("google-cloud-texttospeech is not installed. Install it with: pip install google-cloud-texttospeech")

    if creds_path:
        from google.oauth2 import service_account
        creds_path = Path(creds_path)
        if not creds_path.exists():
            raise FileNotFoundError(f"Service account key file not found: {creds_path}")
        credentials = service_account.Credentials.from_service_account_file(str(creds_path))
    else:
        credentials = None

    client = texttospeech.TextToSpeechClient(credentials=credentials) if credentials else texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)

    language_code = 'en-US'
    if '-' in voice_name:
        parts = voice_name.split('-')
        if len(parts) >= 2:
            language_code = f"{parts[0]}-{parts[1]}"

    voice = texttospeech.VoiceSelectionParams(name=voice_name, language_code=language_code)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    try:
        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        output_path = Path(output_path)
        output_path.write_bytes(response.audio_content)
        return output_path.exists()
    except Exception as e:
        print(f"[ERROR] Google TTS generation failed for {output_path}: {e}")
        return False


def generate_audio_azure(text, voice_name, output_path, azure_key=None, azure_region=None):
    if not AZURE_TTS_AVAILABLE:
        raise ImportError("azure-cognitiveservices-speech is not installed. Install it with: pip install azure-cognitiveservices-speech")
    if not azure_key or not azure_region:
        raise ValueError("Azure TTS requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")

    try:
        speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        speech_config.speech_synthesis_voice_name = voice_name
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            output_path = Path(output_path)
            output_path.write_bytes(result.audio_data)
            return output_path.exists()

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = speechsdk.CancellationDetails(result)
            print(f"[ERROR] Azure TTS canceled for {output_path}: {cancellation.reason} {cancellation.error_details}")
            return False

        print(f"[ERROR] Azure TTS failed for {output_path}: {result.reason}")
        return False
    except Exception as e:
        print(f"[ERROR] Azure TTS generation failed for {output_path}: {e}")
        return False


async def generate_audio(text, voice_name, output_path, tts_service='google', creds_path=None, azure_key=None, azure_region=None):
    tts_service = tts_service.lower()
    if tts_service == 'google':
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, generate_audio_google, text, voice_name, output_path, creds_path)
    if tts_service == 'azure':
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, generate_audio_azure, text, voice_name, output_path, azure_key, azure_region)
    return await generate_audio_edge(text, voice_name, output_path)


def load_stt_model(model_name='tiny'):
    if not WHISPER_AVAILABLE:
        raise ImportError(
            "Whisper is not installed. Install with: pip install openai-whisper\n"
            "Also ensure ffmpeg is installed and available in PATH."
        )
    print(f"Loading Whisper STT model: {model_name}")
    return whisper.load_model(model_name)


def transcribe_audio_simple(audio_path: Path, stt_model) -> str:
    try:
        result = stt_model.transcribe(str(audio_path), fp16=False)
        return (result.get('text') or '').strip()
    except Exception as e:
        print(f"[ERROR] STT failed for {audio_path}: {e}")
        return ''


def initialize_csv(csv_output_path: Path) -> None:
    csv_output_path = Path(csv_output_path)
    csv_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_output_path, 'w', newline='', encoding='utf-8-sig') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(CSV_HEADERS)


def append_csv_rows(csv_output_path: Path, rows: List[List[str]]) -> None:
    with open(csv_output_path, 'a', newline='', encoding='utf-8-sig') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerows(rows)


def finalize_csv_to_excel(csv_output_path: Path, excel_output_path: Path) -> None:
    df = pd.read_csv(csv_output_path)
    df.to_excel(excel_output_path, index=False)


async def process_single_variation(
    utterance_id: int,
    utterance_text: str,
    accent: str,
    gender: str,
    voice_name: Optional[str],
    temp_audio_root: Path,
    stt_model,
    tts_service: str,
    creds_path: Optional[str],
    azure_key: Optional[str],
    azure_region: Optional[str],
    semaphore: asyncio.Semaphore,
):
    async with semaphore:
        if not voice_name:
            return [utterance_id, utterance_text, accent, gender, '', '', 'voice_not_found']

        utterance_dir = temp_audio_root / f'utterance_{utterance_id}'
        utterance_dir.mkdir(parents=True, exist_ok=True)
        audio_file = utterance_dir / f'{utterance_id}_{gender}_{accent}.mp3'

        try:
            success = await generate_audio(
                utterance_text,
                voice_name,
                audio_file,
                tts_service=tts_service,
                creds_path=creds_path,
                azure_key=azure_key,
                azure_region=azure_region,
            )

            if not success or not audio_file.exists():
                return [utterance_id, utterance_text, accent, gender, voice_name, '', 'generation_failed']

            stt_text = transcribe_audio_simple(audio_file, stt_model)
            status = 'success' if stt_text else 'stt_failed'
            return [utterance_id, utterance_text, accent, gender, voice_name, stt_text, status]
        finally:
            try:
                if audio_file.exists():
                    audio_file.unlink()
            except Exception as delete_error:
                print(f"[WARNING] Failed to delete temporary audio {audio_file}: {delete_error}")

            try:
                if utterance_dir.exists() and not any(utterance_dir.iterdir()):
                    utterance_dir.rmdir()
            except Exception:
                pass


async def generate_utterance_variations(
    utterance_id: int,
    utterance_text: str,
    voice_map: Dict[str, Dict[str, str]],
    temp_audio_root: Path,
    csv_output_path: Path,
    stt_model,
    tts_service='google',
    creds_path=None,
    azure_key=None,
    azure_region=None,
    batch_size: int = 4,
):
    semaphore = asyncio.Semaphore(max(1, batch_size))
    tasks = []

    for accent in ACCENTS:
        for gender in GENDERS:
            voice_name = voice_map.get(accent, {}).get(gender)
            tasks.append(
                process_single_variation(
                    utterance_id=utterance_id,
                    utterance_text=utterance_text,
                    accent=accent,
                    gender=gender,
                    voice_name=voice_name,
                    temp_audio_root=temp_audio_root,
                    stt_model=stt_model,
                    tts_service=tts_service,
                    creds_path=creds_path,
                    azure_key=azure_key,
                    azure_region=azure_region,
                    semaphore=semaphore,
                )
            )

    rows = await asyncio.gather(*tasks)
    append_csv_rows(csv_output_path, rows)
    return rows


async def process_excel_file(
    excel_path,
    output_dir,
    limit=None,
    tts_service='google',
    creds_path=None,
    azure_key=None,
    azure_region=None,
    stt_model_name='tiny',
    batch_size=4,
):
    print('=' * 60)
    print('📄 LOADING EXCEL FILE')
    print('=' * 60)

    excel_path = Path(excel_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_excel(excel_path, sheet_name=0)
    if 'Utterance' not in df.columns:
        raise ValueError(f"'Utterance' column not found. Available columns: {list(df.columns)}")

    valid_df = df[df['Utterance'].notna() & (df['Utterance'].astype(str).str.strip() != '')].copy()
    if limit and limit > 0:
        valid_df = valid_df.head(limit)

    print(f'Total valid utterances: {len(valid_df)}')
    print(f'Expected outputs: {len(valid_df) * len(ACCENTS) * len(GENDERS)}')

    print('\n' + '=' * 60)
    print('🔍 DISCOVERING TTS VOICES')
    print('=' * 60)
    voice_map = await discover_voices(tts_service, creds_path, azure_key, azure_region)
    (output_dir / 'voice_mapping.json').write_text(json.dumps(voice_map, indent=2), encoding='utf-8')

    print('\n' + '=' * 60)
    print('🧠 LOADING STT MODEL')
    print('=' * 60)
    stt_model = load_stt_model(stt_model_name)

    csv_output_path = output_dir / 'tts_stt_results.csv'
    excel_output_path = output_dir / 'tts_stt_results.xlsx'
    temp_audio_root = output_dir / 'temp-audio'
    temp_audio_root.mkdir(parents=True, exist_ok=True)
    initialize_csv(csv_output_path)

    all_results = []
    total_utterances = len(valid_df)

    print('\n' + '=' * 60)
    print('🎵 RUNNING TTS -> STT -> CSV PIPELINE')
    print('=' * 60)
    print(f'Parallel batch size: {batch_size}')

    for idx, row in enumerate(valid_df.itertuples(index=False), start=1):
        utterance_text = str(getattr(row, 'Utterance')).strip()
        utterance_id = idx

        print('\n' + '-' * 60)
        print(f'Utterance {utterance_id}/{total_utterances}')
        print(f'Text: {utterance_text}')

        rows = await generate_utterance_variations(
            utterance_id=utterance_id,
            utterance_text=utterance_text,
            voice_map=voice_map,
            temp_audio_root=temp_audio_root,
            csv_output_path=csv_output_path,
            stt_model=stt_model,
            tts_service=tts_service,
            creds_path=creds_path,
            azure_key=azure_key,
            azure_region=azure_region,
            batch_size=batch_size,
        )
        all_results.extend(rows)
        success_count = sum(1 for r in rows if r[-1] == 'success')
        print(f'Completed utterance {utterance_id}: {success_count}/{len(rows)} successful')

    print('\nFinalizing Excel export...')
    finalize_csv_to_excel(csv_output_path, excel_output_path)

    try:
        if temp_audio_root.exists() and not any(temp_audio_root.iterdir()):
            temp_audio_root.rmdir()
    except Exception:
        pass

    successful_count = sum(1 for r in all_results if r[-1] == 'success')
    return {
        'total_files': successful_count,
        'total_expected': len(valid_df) * len(ACCENTS) * len(GENDERS),
        'utterances_processed': len(valid_df),
        'csv_output': str(csv_output_path),
        'excel_output': str(excel_output_path),
        'voice_mapping': voice_map,
        'stt_model': stt_model_name,
        'batch_size': batch_size,
    }


def generate_audio_files(
    excel_path,
    output_dir,
    limit=None,
    tts_service='google',
    creds_path=None,
    azure_key=None,
    azure_region=None,
    stt_model_name='tiny',
    batch_size=4,
):
    return asyncio.run(
        process_excel_file(
            excel_path=excel_path,
            output_dir=output_dir,
            limit=limit,
            tts_service=tts_service,
            creds_path=creds_path,
            azure_key=azure_key,
            azure_region=azure_region,
            stt_model_name=stt_model_name,
            batch_size=batch_size,
        )
    )
