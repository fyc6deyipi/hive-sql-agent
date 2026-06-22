import requests
import json


def main():
        
    url = "https://qianfan.baidubce.com/v2/app/conversation"
    
    payload = json.dumps({
        "app_id": "08cdb1fa-ed75-4dcf-a29e-6867faf29dda"
    }, ensure_ascii=False)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer '
    }
    
    response = requests.request("POST", url, headers=headers, data=payload.encode("utf-8"))
    
    response.encoding = "utf-8"
    print(response.text)
    

if __name__ == '__main__':
    main()
