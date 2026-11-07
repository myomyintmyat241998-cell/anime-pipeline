import requests

def upload_video_to_vk(video_path, title, group_id, access_token):
    url = "https://api.vk.com/method/video.save"
    
    # VK API Parameters
    params = {
        'access_token': access_token,
        'v': '5.131',
        'group_id': group_id,
        'name': title,
        'description': 'Uploaded via automated pipeline',
        'wallpost': 0,        # Group Wall ပေါ်မှာ တင်မည်မဟုတ် (0 = No wall post)
        'privacy_view': 'all' # သို့မဟုတ် လိုအပ်သော privacy သတ်မှတ်ချက်
    }
    
    response = requests.post(url, data=params).json()
    
    if 'response' in response:
        upload_url = response['response']['upload_url']
        video_id = response['response']['video_id']
        owner_id = response['response']['owner_id']
        
        # ဗီဒီယိုဖိုင်ကို upload_url သို့ ပို့ဆောင်ခြင်း
        with open(video_path, 'rb') as f:
            files = {'video_file': f}
            requests.post(upload_url, files=files)
            
        print(f"Video uploaded successfully! ID: video{owner_id}_{video_id}")
        return f"https://vk.com/video{owner_id}_{video_id}"
    else:
        print("VK Upload Error:", response)
        return None
