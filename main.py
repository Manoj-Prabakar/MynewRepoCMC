"""
Main Orchestrator Script for Dialogflow CX Audio Testing
Coordinates TTS generation, Dialogflow testing, and report generation

PROPRIETARY NOTICE:
This code is proprietary and belongs to Miratech & Nikhil Kodilkar.
Copyright (c) Miratech & Nikhil Kodilkar. All rights reserved.
Contact: Nikhil.Kodilkar@miratechgroup.com
"""

# HIGH-LEVEL FLOW:
# 1. Load configuration from BOT-TO-TEST-CONFIGURATION-INFO.txt
# 2. Create output directory
# 3. Step 1: Generate TTS audio files from Excel utterances
# 4. Step 2: Test audio files with Dialogflow CX
# 5. Step 3: Generate report from TTS and test results
# 6. Display summary
# 7. Test command line: python main.py sample-utterance.xlsx [--config-file PATH] [--output-dir DIR] [--limit N] [--skip-tts] [--skip-testing]
#    Note: config-file and output-dir paths are relative to main.py directory

import os
import sys
import argparse
from pathlib import Path
import json

# Add modules directory to path
sys.path.insert(0, str(Path(__file__).parent))

from modules.tts_generator import generate_audio_files
from modules.dialogflow_client import DialogflowClient
from modules.audio_tester import test_audio_files
from modules.report_generator import generate_report
from modules.config_loader import load_config
import shutil
import os

print(os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe"))

os.environ["path"] += os.pathsep + r"C:\\ffmpeg\\bin\\"

from pydub import AudioSegment
#AudioSegment.converter = r"C:\ffmpeg\bin\ffmpeg.exe"
#AudioSegment.ffmpeg = r"C:\ffmpeg\bin\ffmpeg.exe"
#AudioSegment.ffprobe = r"C:\ffmpeg\bin\ffprobe.exe"
print('*******************printing ffprobe****************')
print(shutil.which("ffmpeg"))

# Amazon Lex imports (optional - only imported if platform is amazon_lex)
try:
    from modules.amazon_lex_client import AmazonLexClient
    from modules.amazon_lex_tester import test_audio_files as test_audio_files_lex
    AMAZON_LEX_AVAILABLE = True
except ImportError:
    AMAZON_LEX_AVAILABLE = False

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass


def main():
    parser = argparse.ArgumentParser(
        description='Dialogflow CX Audio Testing Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python main.py sample-utterance.xlsx
  
  # Configuration is read from BOT-TO-TEST-CONFIGURATION-INFO.txt
  # Make sure to update that file with your Dialogflow CX settings first
        """
    )
    
    # Required arguments
    parser.add_argument('excel_file', help='Path to Excel file with utterances')
    parser.add_argument('--config-file', default='BOT-TO-TEST-CONFIGURATION-INFO.txt', 
                       help='Path to configuration file (default: BOT-TO-TEST-CONFIGURATION-INFO.txt in audio-service directory)')
    
    # Optional arguments
    parser.add_argument('--output-dir', default='test-output', help='Output directory for generated files')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of utterances to process (for testing)')
    parser.add_argument('--skip-tts', action='store_true', 
                       help='Skip TTS generation if audio files already exist')
    parser.add_argument('--skip-testing', action='store_true',
                       help='Skip Dialogflow testing (only generate audio)')
    
    args = parser.parse_args()
    
    # Validate Excel file
    excel_path = Path(args.excel_file)
    if not excel_path.exists():
        print(f"❌ Error: Excel file not found: {excel_path}")
        return 1
    
    # Load configuration from file
    try:
        print("="*70)
        print("LOADING CONFIGURATION")
        print("="*70)
        config = load_config(args.config_file)
        print("="*70)
        print()
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        return 1
    except ValueError as e:
        print(f"❌ Error: {e}")
        return 1
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("="*70)
    print("DIALOGFLOW CX AUDIO TESTING PIPELINE")
    print("="*70)
    print(f"Excel file: {excel_path.absolute()}")
    print(f"Output directory: {output_dir.absolute()}")
    print(f"Project ID: {config['PROJECT_ID']}")
    print(f"Location: {config['LOCATION']}")
    print(f"Agent ID: {config['AGENT_ID']}")
    if config.get('FLOW_ID'):
        print(f"Flow ID: {config['FLOW_ID']}")
    if config.get('PAGE_ID'):
        print(f"Page ID: {config['PAGE_ID']}")
    print(f"Start with greeting: {config.get('START_WITH_GREETING', False)}")
    print("="*70)
    print()
    
    results = {
        'tts_generation': None,
        'dialogflow_testing': None,
        'report': None
    }
    
    # Step 1: Generate TTS Audio Files
    if not args.skip_tts:
        print("\n" + "="*70)
        print("STEP 1: GENERATING TTS AUDIO FILES")
        print("="*70)
        try:
            print(f"[DEBUG] Calling generate_audio_files with:")
            print(f"  excel_path: {excel_path}")
            print(f"  output_dir: {output_dir}")
            print(f"  limit: {args.limit}")
            
            tts_service = config.get('TTS_SERVICE', 'google').lower()
            if tts_service not in ['edge', 'google', 'azure']:
                print(f"[WARNING] Invalid TTS_SERVICE: {tts_service}. Using 'google' as default.")
                tts_service = 'google'
            
            print(f"[DEBUG] Using TTS service: {tts_service.upper()}")
            
            # Pass credentials based on TTS service
            creds_path = config.get('CREDS_PATH') if tts_service == 'google' else None
            azure_key = config.get('AZURE_SPEECH_KEY') if tts_service == 'azure' else None
            azure_region = config.get('AZURE_SPEECH_REGION') if tts_service == 'azure' else None
            
            tts_results = generate_audio_files(
                excel_path=excel_path,
                output_dir=output_dir,
                limit=args.limit,
                tts_service=tts_service,
                creds_path=creds_path,
                azure_key=azure_key,
                azure_region=azure_region
            )
            
            if tts_results is None:
                print("\n❌ TTS generation returned None - check logs above for errors")
                return 1
            
            results['tts_generation'] = tts_results
            
            # Save TTS results to JSON
            tts_results_file = output_dir / 'tts_results.json'
            print(f"[DEBUG] Saving TTS results to: {tts_results_file}")
            try:
                with open(tts_results_file, 'w') as f:
                    json.dump(tts_results, f, indent=2)
                print(f"[DEBUG] TTS results saved successfully")
            except Exception as save_error:
                print(f"[WARNING] Failed to save TTS results: {save_error}")
            
            print(f"\n✓ TTS generation completed: {tts_results.get('total_files', 0)} files generated")
        except Exception as e:
            print(f"\n❌ TTS generation failed: {e}")
            import traceback
            traceback.print_exc()
            return 1
    else:
        print("\n⏭ Skipping TTS generation (--skip-tts)")
        # Load existing TTS results if available
        tts_results_file = output_dir / 'tts_results.json'
        if tts_results_file.exists():
            with open(tts_results_file, 'r') as f:
                results['tts_generation'] = json.load(f)
        else:
            print("⚠ Warning: No existing TTS results found. Audio files may not exist.")
    
    # Step 2: Test Audio Files with Bot Platform
    if not args.skip_testing:
        platform = config.get('PLATFORM', 'dialogflow').lower()
        
        if platform == 'dialogflow':
            # ===================================================================
            # DIALOGFLOW CX TESTING - EXISTING CODE (UNCHANGED)
            # ===================================================================
            print("\n" + "="*70)
            print("STEP 2: TESTING AUDIO FILES WITH DIALOGFLOW CX")
            print("="*70)
            
            # Initialize Dialogflow client
            try:
                dialogflow_client = DialogflowClient(
                    project_id=config['PROJECT_ID'],
                    location=config['LOCATION'],
                    agent_id=config['AGENT_ID']
                    #creds_path=config['CREDS_PATH']
                )

                #conversation = DialogflowConversation(agent_id=agent_id)
                print("✓ Dialogflow client initialized")
            except Exception as e:
                print(f"❌ Failed to initialize Dialogflow client: {e}")
                return 1
            
            # Test audio files
            try:
                audio_dir = output_dir / 'dialogflow-ready'
                print(f"[DEBUG] Audio directory: {audio_dir}")
                print(f"[DEBUG] Audio directory exists: {audio_dir.exists()}")
                
                if not audio_dir.exists():
                    print(f"❌ Error: Audio directory does not exist: {audio_dir}")
                    print(f"  Run TTS generation first or check output directory")
                    return 1
                
                print(f"[DEBUG] Calling test_audio_files with:")
                print(f"  audio_dir: {audio_dir}")
                print(f"  start_with_greeting: {config.get('START_WITH_GREETING', False)}")
                print(f"  flow_id: {config.get('FLOW_ID')}")
                print(f"  page_id: {config.get('PAGE_ID')}")
                
                test_results = test_audio_files(
                    dialogflow_client=dialogflow_client,
                    audio_dir=audio_dir,
                    start_with_greeting=config.get('START_WITH_GREETING', False),
                    flow_id=config.get('FLOW_ID'),
                    page_id=config.get('PAGE_ID')
                )
                
                if test_results is None:
                    print("\n❌ Dialogflow testing returned None - check logs above for errors")
                    return 1
                
                results['dialogflow_testing'] = test_results
                
                # Save test results to JSON
                test_results_file = output_dir / 'test_results.json'
                print(f"[DEBUG] Saving test results to: {test_results_file}")
                try:
                    with open(test_results_file, 'w') as f:
                        json.dump(test_results, f, indent=2)
                    print(f"[DEBUG] Test results saved successfully")
                except Exception as save_error:
                    print(f"[WARNING] Failed to save test results: {save_error}")
                
                print(f"\n✓ Dialogflow testing completed: {test_results.get('total_tested', 0)} files tested")
            except Exception as e:
                print(f"\n❌ Dialogflow testing failed: {e}")
                import traceback
                traceback.print_exc()
                return 1
        
        elif platform == 'amazon_lex':
            # ===================================================================
            # AMAZON LEX TESTING - NEW CODE PATH
            # ===================================================================
            if not AMAZON_LEX_AVAILABLE:
                print("\n❌ Error: Amazon Lex modules not available")
                print("  Make sure amazon_lex_client.py and amazon_lex_tester.py exist")
                return 1
            
            print("\n" + "="*70)
            print("STEP 2: TESTING AUDIO FILES WITH AMAZON LEX")
            print("="*70)
            
            # Initialize Amazon Lex client
            try:
                lex_client = AmazonLexClient(
                    bot_id=config['LEX_BOT_ID'],
                    bot_alias_id=config['LEX_BOT_ALIAS_ID'],
                    locale_id=config['LEX_LOCALE_ID'],
                    aws_region=config['AWS_REGION'],
                    aws_access_key_id=config.get('AWS_ACCESS_KEY_ID'),
                    aws_secret_access_key=config.get('AWS_SECRET_ACCESS_KEY')
                )
                print("✓ Amazon Lex client initialized")
            except Exception as e:
                print(f"❌ Failed to initialize Amazon Lex client: {e}")
                return 1
            
            # Test audio files
            try:
                audio_dir = output_dir / 'dialogflow-ready'  # Reuse same directory name
                print(f"[DEBUG] Audio directory: {audio_dir}")
                print(f"[DEBUG] Audio directory exists: {audio_dir.exists()}")
                
                if not audio_dir.exists():
                    print(f"❌ Error: Audio directory does not exist: {audio_dir}")
                    print(f"  Run TTS generation first or check output directory")
                    return 1
                
                print(f"[DEBUG] Calling test_audio_files_lex with:")
                print(f"  audio_dir: {audio_dir}")
                print(f"  start_with_greeting: {config.get('START_WITH_GREETING', False)}")
                
                test_results = test_audio_files_lex(
                    lex_client=lex_client,
                    audio_dir=audio_dir,
                    start_with_greeting=config.get('START_WITH_GREETING', False)
                )
                
                if test_results is None:
                    print("\n❌ Amazon Lex testing returned None - check logs above for errors")
                    return 1
                
                results['dialogflow_testing'] = test_results  # Reuse same key for compatibility
                
                # Save test results to JSON
                test_results_file = output_dir / 'test_results.json'
                print(f"[DEBUG] Saving test results to: {test_results_file}")
                try:
                    with open(test_results_file, 'w') as f:
                        json.dump(test_results, f, indent=2)
                    print(f"[DEBUG] Test results saved successfully")
                except Exception as save_error:
                    print(f"[WARNING] Failed to save test results: {save_error}")
                
                print(f"\n✓ Amazon Lex testing completed: {test_results.get('total_tested', 0)} files tested")
            except Exception as e:
                print(f"\n❌ Amazon Lex testing failed: {e}")
                import traceback
                traceback.print_exc()
                return 1
        
        else:
            print(f"\n❌ Error: Unknown platform: {platform}")
            print(f"  Supported platforms: 'dialogflow', 'amazon_lex'")
            return 1
    else:
        print("\n⏭ Skipping Dialogflow testing (--skip-testing)")
        # Load existing test results if available
        test_results_file = output_dir / 'test_results.json'
        if test_results_file.exists():
            with open(test_results_file, 'r') as f:
                results['dialogflow_testing'] = json.load(f)
    
    # Step 3: Generate Report
    if results.get('dialogflow_testing'):
        print("\n" + "="*70)
        print("STEP 3: GENERATING REPORT")
        print("="*70)
        try:
            print(f"[DEBUG] Calling generate_report with:")
            print(f"  tts_results: {results['tts_generation'] is not None}")
            print(f"  test_results: {results['dialogflow_testing'] is not None}")
            print(f"  output_dir: {output_dir}")
            print(f"  excel_path: {excel_path}")
            
            report_path = generate_report(
                tts_results=results['tts_generation'],
                test_results=results['dialogflow_testing'],
                output_dir=output_dir,
                excel_path=excel_path
            )
            
            if report_path is None:
                print("\n❌ Report generation returned None - check logs above for errors")
                return 1
            
            results['report'] = str(report_path)
            print(f"\n✓ Report generated: {report_path.absolute()}")
        except Exception as e:
            print(f"\n❌ Report generation failed: {e}")
            import traceback
            traceback.print_exc()
            return 1
    else:
        print("\n⏭ Skipping report generation (no test results available)")
    
    # Summary
    print("\n" + "="*70)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("="*70)
    print(f"Output directory: {output_dir.absolute()}")
    if results.get('report'):
        print(f"Report: {results['report']}")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

