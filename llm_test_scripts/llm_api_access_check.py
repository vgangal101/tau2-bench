from openai import OpenAI  # pip install openai
import os 

#intel_llm_key = os.environ['intel_llm_key']
#client = OpenAI(base_url="https://openai.rc.asu.edu/v1", api_key=intel_llm_key)
#print('client built')

client = OpenAI(base_url=os.environ['OPENAI_BASE_URL'],api_key=os.environ['OPENAI_API_KEY'],timeout=180,max_retries=0)
response = client.chat.completions.create(
    model="glm-5-2",
    messages=[
        {"role": 'system', 'content': "Respond in English"},
        {"role": "user", "content": "Hello!"}],
)
print('after response')
print(response.choices[0].message.content)