import os
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler
from pytube import YouTube
import ffmpeg
import logging

# Enable logging for debugging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Define states for conversation
URL, FORMAT, RESOLUTION = range(3)

# Start command
def start(update, context):
    update.message.reply_text(
        "Welcome to the YouTube Downloader Bot! Send a YouTube URL to begin."
    )
    return URL

# Receive and validate YouTube URL
def receive_url(update, context):
    url = update.message.text
    try:
        yt = YouTube(url)
        context.user_data['video'] = yt
        update.message.reply_text(
            f"Got it! Video: {yt.title}\nChoose format: /video (MP4) or /audio (MP3)"
        )
        return FORMAT
    except Exception as e:
        update.message.reply_text(f"Error: Invalid URL or issue fetching video. Try again. ({str(e)})")
        return URL

# Handle format selection (video or audio)
def select_video(update, context):
    yt = context.user_data.get('video')
    if not yt:
        update.message.reply_text("No video selected. Send a YouTube URL first.")
        return URL

    try:
        # Get all progressive MP4 streams (video + audio)
        streams = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()
        if not streams:
            update.message.reply_text("No MP4 video streams available for this video.")
            return URL

        # List available resolutions
        context.user_data['streams'] = streams
        response = "Available resolutions:\n"
        for i, stream in enumerate(streams, 1):
            res = stream.resolution or "Unknown"
            fps = stream.fps
            size_mb = stream.filesize / (1024 * 1024)  # Convert bytes to MB
            response += f"{i}. {res} @ {fps}fps ({size_mb:.2f} MB) - /res_{res}\n"

        response += "\nSelect a resolution by typing the command (e.g., /res_1080p)."
        update.message.reply_text(response)
        return RESOLUTION
    except Exception as e:
        update.message.reply_text(f"Error fetching streams: {str(e)}")
        return URL

# Download and send video for selected resolution
def download_video(update, context):
    yt = context.user_data.get('video')
    streams = context.user_data.get('streams')
    if not yt or not streams:
        update.message.reply_text("No video or streams selected. Send a YouTube URL first.")
        return URL

    # Extract resolution from command (e.g., /res_1080p -> 1080p)
    command = update.message.text
    resolution = command.split('_')[-1] if '_' in command else None
    if not resolution:
        update.message.reply_text("Invalid resolution command. Use /res_<resolution> (e.g., /res_1080p).")
        return RESOLUTION

    try:
        # Find stream matching the resolution
        stream = next((s for s in streams if s.resolution == resolution), None)
        if not stream:
            update.message.reply_text(f"No stream found for {resolution}. Try another resolution.")
            return RESOLUTION

        # Check file size (Telegram limit: 50MB for free bots)
        size_mb = stream.filesize / (1024 * 1024)
        if size_mb > 50:
            update.message.reply_text(
                f"File size ({size_mb:.2f} MB) exceeds Telegram's 50MB limit for free bots. "
                "Choose a lower resolution or /cancel."
            )
            return RESOLUTION

        # Download to temporary storage
        file_path = stream.download(output_path="downloads")
        update.message.reply_text(f"Downloaded {resolution} video! Sending...")

        # Send video to Telegram
        with open(file_path, 'rb') as video:
            update.message.reply_video(video, timeout=120)

        # Clean up
        os.remove(file_path)
        update.message.reply_text("Done! Send another URL or /cancel to stop.")
        return URL
    except Exception as e:
        update.message.reply_text(f"Error downloading video: {str(e)}")
        return RESOLUTION

# Download and convert to MP3
def download_audio(update, context):
    yt = context.user_data.get('video')
    if not yt:
        update.message.reply_text("No video selected. Send a YouTube URL first.")
        return URL

    try:
        # Download audio stream
        stream = yt.streams.filter(only_audio=True).first()
        if not stream:
            update.message.reply_text("No audio stream available.")
            return URL

        # Download to temporary storage
        file_path = stream.download(output_path="downloads")
        mp3_path = file_path.replace('.mp4', '.mp3')

        # Check file size
        size_mb = stream.filesize / (1024 * 1024)
        if size_mb > 50:
            update.message.reply_text(
                f"File size ({size_mb:.2f} MB) exceeds Telegram's 50MB limit for free bots. "
                "Try /cancel and select a different video."
            )
            os.remove(file_path)
            return URL

        # Convert to MP3 using ffmpeg
        ffmpeg.input(file_path).output(mp3_path, format='mp3', audio_bitrate='192k').run()

        # Send MP3 to Telegram
        with open(mp3_path, 'rb') as audio:
            update.message.reply_audio(audio, timeout=120)

        # Clean up
        os.remove(file_path)
        os.remove(mp3_path)
        update.message.reply_text("Done! Send another URL or /cancel to stop.")
        return URL
    except Exception as e:
        update.message.reply_text(f"Error processing audio: {str(e)}")
        return URL

# Cancel the conversation
def cancel(update, context):
    update.message.reply_text("Operation cancelled. Use /start to begin again.")
    context.user_data.clear()
    return ConversationHandler.END

# Error handler
def error(update, context):
    update.message.reply_text(f"An error occurred: {context.error}")
    logging.error(f"Update caused error: {context.error}")

# Main function to set up the bot
def main():
    # Use environment variable for token
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN not set in environment variables.")

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    # Create conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            URL: [MessageHandler(Filters.text & ~Filters.command, receive_url)],
            FORMAT: [
                CommandHandler('video', select_video),
                CommandHandler('audio', download_audio),
            ],
            RESOLUTION: [MessageHandler(Filters.command, download_video)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # Add handlers
    dp.add_handler(conv_handler)
    dp.add_error_handler(error)

    # Create downloads directory
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()