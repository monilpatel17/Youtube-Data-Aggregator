from django.shortcuts import render
from googleapiclient.discovery import build
import isodate
import os
import seaborn as sns
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import boto3
from io import BytesIO
import base64
from django.utils import timezone
import pytz
from django.utils.dateparse import parse_datetime


def iso8601_duration_to_seconds(duration_str):
    duration = isodate.parse_duration(duration_str)
    return int(duration.total_seconds())

def convert_to_est(date_time_str):
    date_time_obj = parse_datetime(date_time_str)
    if date_time_obj is not None:
        if date_time_obj.tzinfo is None:
            utc_timezone = pytz.timezone('UTC')
            date_time_obj = utc_timezone.localize(date_time_obj)
            
        est_timezone = pytz.timezone('America/New_York')
        return date_time_obj.astimezone(est_timezone)
    else:
        raise ValueError("Invalid datetime format")

def get_youtube_data(api_key, channel_id):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.channels().list(
        part='snippet,contentDetails,statistics',
        id=channel_id
    )
    response = request.execute()
    if not response['items']:
        return {}  # Or handle the lack of data appropriately

    channel_data = response['items'][0]
    creation_date = convert_to_est(channel_data['snippet']['publishedAt']).strftime('%Y-%m-%d %H:%M:%S %Z%z')

    channel_info = {
        'id': channel_data['id'],
        'title': channel_data['snippet']['title'],
        'description': channel_data['snippet']['description'],
        'creation_date': creation_date,
        'subscriberCount': channel_data['statistics']['subscriberCount'],
        'viewCount': channel_data['statistics']['viewCount'],
        'videoCount': channel_data['statistics']['videoCount'],
    }
    return channel_info

def get_playlist_details(api_key, channel_id):
    youtube = build('youtube', 'v3', developerKey=api_key)
    playlists_request = youtube.playlists().list(part='snippet,contentDetails', channelId=channel_id, maxResults=25)
    playlists_response = playlists_request.execute()
    playlists = []

    for playlist in playlists_response.get('items', []):
        playlist_id = playlist['id']
        playlist_title = playlist['snippet']['title']
        number_of_videos = playlist['contentDetails']['itemCount']
        creation_time = playlist['snippet']['publishedAt']
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        playlist_id = playlist['id']
        playlist_thumbnail = playlist['snippet']['thumbnails']['high']['url']
        playlist['videos'] = get_playlist_videos(youtube, playlist_id)
        creation_time_est = convert_to_est(creation_time)
        est_time = creation_time_est.strftime('%Y-%m-%d %H:%M:%S %Z%z') if creation_time_est else 'Timezone conversion error'

        total_views = 0
        total_duration_seconds = 0

        playlist_items_request = youtube.playlistItems().list(part='contentDetails', playlistId=playlist_id, maxResults=50)
        while playlist_items_request:
            playlist_items_response = playlist_items_request.execute()

            video_ids = [item['contentDetails']['videoId'] for item in playlist_items_response.get('items', [])]

            if video_ids:
                videos_request = youtube.videos().list(part='contentDetails,statistics', id=','.join(video_ids))
                videos_response = videos_request.execute()

                for video in videos_response.get('items', []):
                    duration_str = video['contentDetails']['duration']
                    total_duration_seconds += iso8601_duration_to_seconds(duration_str)

                    view_count = video['statistics'].get('viewCount', 0)
                    total_views += int(view_count)

            playlist_items_request = youtube.playlistItems().list_next(playlist_items_request, playlist_items_response)

        # Convert total duration from seconds to hours and round to 2 decimal places
        total_duration_hours = round(total_duration_seconds / 3600, 2)
        timezone_now = creation_time
        est_time = convert_to_est(timezone_now)
        est_time = str(est_time)
        
        playlists.append({
            'title': playlist_title,
            'number_of_videos': number_of_videos,
            'total_duration_seconds': total_duration_hours,  # This should be in hours according to the graph function
            'creation_time': est_time,
            'total_views': total_views,
            'url': playlist_url,
            'thumbnail': playlist_thumbnail,
        })

    return playlists

def get_channel_id(channel_name, api_key):
    # Build a YouTube client
    youtube = build('youtube', 'v3', developerKey=api_key)

    # Search for channels by name
    request = youtube.search().list(
        q=channel_name,
        part='snippet',
        type='channel',
        maxResults=1
    )
    response = request.execute()

    # Check if there are results
    if response['items']:
        # Return the channel ID
        return response['items'][0]['snippet']['channelId']
    else:
        return "No channel found with that name."

def index(request):
    api_key = 'AIzaSyDB0Q54lmD00KYA8oIfZc5CFsOutG0QZuo'
    # channel_id = 'UCfJyQ3P2k_SuqfxVdqIEQNw'
    channel_name = request.GET.get('channel_id', None)
    channel_id = get_channel_id(channel_name, api_key)

    context = {'channel_info': None, 'playlists': None, 'graph_image_base64': None}

    if channel_id:
        channel_info = get_youtube_data(api_key, channel_id)
        playlists = get_playlist_details(api_key, channel_id)
        video_details = get_video_details(api_key, channel_id)
        graph_image_base64 = graph(playlists, video_details)

        context = {
            'channel_info': channel_info,
            'playlists': playlists,
            'graph_image_base64': graph_image_base64,
        }

    return render(request, 'map.html', context)

  

def get_video_details(api_key, channel_id):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.search().list(part="snippet", channelId=channel_id, maxResults=50, order="viewCount", type="video")
    response = request.execute()
    video_details = {}
    for item in response['items']:
        video_id = item['id']['videoId']
        video_title = item['snippet']['title']
        video_request = youtube.videos().list(part="statistics,contentDetails", id=video_id)
        video_response = video_request.execute()

        view_count = int(video_response['items'][0]['statistics']['viewCount'])
        duration = iso8601_duration_to_seconds(video_response['items'][0]['contentDetails']['duration'])
        duration = duration/60
        video_details[video_title] = {'views': view_count, 'duration': duration}

    return video_details

    



def graph(playlists, video_details):
    sns.set(style="whitegrid")
    plt.figure(figsize=(15, 10))

    # Plot the top 5 playlists by views
    top_playlists = sorted(playlists, key=lambda x: x['total_views'], reverse=True)[:5]
    plt.subplot(2, 2, 1)
    plt.title('Top 5 Playlists by Views')
    playlist_labels = [split_label(playlist['title']) for playlist in top_playlists]
    sns.barplot(x=playlist_labels, y=[playlist['total_views'] for playlist in top_playlists])
    plt.xticks(rotation=0)

    # Plot the top 5 videos by views
    top_videos = sorted(video_details.items(), key=lambda item: item[1]['views'], reverse=True)[:5]
    plt.subplot(2, 2, 2)
    plt.title('Top 5 Videos by Views')
    video_labels = [split_label(video[0]) for video in top_videos]
    sns.barplot(x=video_labels, y=[video[1]['views'] for video in top_videos])
    plt.xticks(rotation=0)

    # Scatter plot for video duration vs views
    plt.subplot(2, 2, 3)
    sns.scatterplot(x=[details['duration'] for details in video_details.values()], y=[details['views'] for details in video_details.values()])
    plt.title('Duration vs Popularity (Videos)')
    plt.xlabel('Duration (minutes)')
    plt.ylabel('Views')

    # Scatter plot for playlist duration vs views
    plt.subplot(2, 2, 4)
    sns.scatterplot(x=[playlist['total_duration_seconds'] for playlist in playlists], y=[playlist['total_views'] for playlist in playlists])
    plt.title('Duration vs Popularity (Playlists)')
    plt.xlabel('Duration (hours)')
    plt.ylabel('Views')

    plt.tight_layout()

    # Save the plot to a BytesIO object
    img_data = BytesIO()
    plt.savefig(img_data, format='png', bbox_inches='tight')
    img_data.seek(0)  # Go to the beginning of the BytesIO buffer

    # Encode the image in base64 and return it
    base64_img = base64.b64encode(img_data.getvalue()).decode()
    img_data.close()  # Close the buffer

    return base64_img

def split_label(label, max_words_per_line=1):
    words = label.split()
    # Split the label into chunks of `max_words_per_line` words each
    split_labels = ['\n'.join(words[i:i + max_words_per_line]) for i in range(0, len(words), max_words_per_line)]
    return '\n'.join(split_labels)



# api_key = 'AIzaSyDB0Q54lmD00KYA8oIfZc5CFsOutG0QZuo'  # Replace with your API key
#     channel_id = 'UCvjXo25nY-WMCTEXZZb0xsw' # Replace with the YouTube channel ID
   
def get_playlist_videos(youtube, playlist_id):
    videos = []
    playlist_items_request = youtube.playlistItems().list(
        part='snippet',
        playlistId=playlist_id,
        maxResults=50
    )
    
    while playlist_items_request:
        playlist_items_response = playlist_items_request.execute()
        
        for item in playlist_items_response.get('items', []):
            video_id = item['snippet']['resourceId']['videoId']
            video_title = item['snippet']['title']
            thumbnails = item['snippet'].get('thumbnails', {})
            video_thumbnail = thumbnails.get('default', {}).get('url', 'default_thumbnail_url_here')
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            videos.append({
                'id': video_id,
                'title': video_title,
                'thumbnail': video_thumbnail,
                'url': video_url
            })
        
        playlist_items_request = youtube.playlistItems().list_next(playlist_items_request, playlist_items_response)
    
    return videos


