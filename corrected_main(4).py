
"""
Main runner for low-storage TTS -> STT pipeline.
Preserves the original TTS generation module logic and only changes post-processing.
"""

import argparse
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))



def load_config(config_file):
    """Simple config loader for KEY = VALUE formatted text files."""
    config_path = Path(config_file)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = {}
    for raw_line in config_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()

        if '#' in value:
            value = value.split('#', 1)[0].rstrip()

        if not value:
            parsed = ''
        else:
            try:
                parsed = ast.literal_eval(value)
            except Exception:
                parsed = value.strip('"').strip("'")

        config[key] = parsed

    return config


def main():
    parser = argparse.ArgumentParser(
        description='Low-storage TTS -> STT pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python corrected_main.py sample-utterance.xlsx
  python corrected_main.py sample-utterance.xlsx --batch-size 4 --stt-model tiny
        """,
    )

    parser.add_argument('excel_file', help='Path to Excel file with utterances')
    parser.add_argument('--config-file', default='BOT-TO-TEST-CONFIGURATION-INFO.txt', help='Path to config file')
    parser.add_argument('--output-dir', default='test-output', help='Output directory for generated result files')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of utterances to process')
    parser.add_argument('--batch-size', type=int, default=4, help='How many audio files to process concurrently')
    parser.add_argument('--stt-model', default='tiny', help='Whisper model name: tiny, base, small, medium, large')

    args = parser.parse_args()

    excel_path = Path(args.excel_file)
    if not excel_path.exists():
        print(f"❌ Error: Excel file not found: {excel_path}")
        return 1

    try:
        print('=' * 70)
        print('LOADING CONFIGURATION')
        print('=' * 70)
        config = load_config(args.config_file)
        print('=' * 70)
        print()
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tts_service = str(config.get('TTS_SERVICE', 'google')).lower()
    if tts_service not in ['edge', 'google', 'azure']:
        print(f"[WARNING] Invalid TTS_SERVICE: {tts_service}. Using 'google' as default.")
        tts_service = 'google'

    creds_path = config.get('CREDS_PATH') if tts_service == 'google' else None
    azure_key = config.get('AZURE_SPEECH_KEY') if tts_service == 'azure' else None
    azure_region = config.get('AZURE_SPEECH_REGION') if tts_service == 'azure' else None

    print('=' * 70)
    print('LOW-STORAGE TTS → STT PIPELINE')
    print('=' * 70)
    print(f"Excel file: {excel_path.resolve()}")
    print(f"Config file: {Path(args.config_file).resolve()}")
    print(f"Output directory: {output_dir.resolve()}")
    print(f"TTS service: {tts_service.upper()}")
    print(f"STT model: {args.stt_model}")
    print(f"Batch size: {args.batch_size}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print('=' * 70)
    print()

    try:
        from corrected_tts_generator import generate_audio_files

        results = generate_audio_files(
            excel_path=excel_path,
            output_dir=output_dir,
            limit=args.limit,
            tts_service=tts_service,
            creds_path=creds_path,
            azure_key=azure_key,
            azure_region=azure_region,
            stt_model_name=args.stt_model,
            batch_size=args.batch_size,
        )
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    if results is None:
        print('❌ Pipeline returned no results')
        return 1

    results_file = output_dir / 'tts_stt_results.json'
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print('\n' + '=' * 70)
    print('PIPELINE COMPLETED SUCCESSFULLY')
    print('=' * 70)
    print(f"Utterances processed: {results.get('utterances_processed', 0)}")
    print(f"Successful outputs: {results.get('total_files', 0)} / {results.get('total_expected', 0)}")
    print(f"CSV output: {results.get('csv_output')}")
    print(f"Excel output: {results.get('excel_output')}")
    print(f"JSON summary: {results_file}")
    print()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
