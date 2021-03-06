from datetime import datetime
from flask import g, request
from flask_restful import Resource, reqparse
import json
import pika

from api import auth, mongo
from core.glados import Glados
from core.utils import *
import os

help_agent = Glados()

test_account_info = {
  'name': 'Nikes',
  'balance': 323710.38,
  'account_no': 12900989124,
  'phone': 73710203,
  'reward_points':525,
  'reward_points_expiring':200,
  'reward_points_expiring_on': '15-09-2016'
}
  
parser = reqparse.RequestParser()
parser.add_argument('text',required=False,type=str)

agent_response_body = None
data_filename = "../../core/res/rewards.txt"
connection = pika.BlockingConnection(pika.ConnectionParameters(
            host='localhost'))

def on_response(ch, method, properties, body):
  global agent_response_body
  print("*****Response %r" % body)
  agent_response_body = body.decode('utf-8')
  ch.basic_ack(delivery_tag = method.delivery_tag)
    
def response_consumer():
  global connection
  resonse_channel = connection.channel()
  resonse_channel.basic_qos(prefetch_count=1)
  resonse_channel.queue_declare(queue='agent_response_queue', durable=True)
  resonse_channel.basic_consume(on_response,queue='agent_response_queue')
  print("Spawining agent response queue")
  resonse_channel.start_consuming()

class HelpApi(Resource):
  def __init__(self):
    global connection
    self.bot_responses = mongo.db.bot_responses
    try:
      self.channel = connection.channel()
      self.channel.queue_declare(queue='task_queue', durable=True)
    except Exception as e:
      print(e)
    
  # method_decorators = [auth.login_required]
  def post(self):
    CURR_PATH = os.path.dirname(__file__)
    args = parser.parse_args()
    input_text = args['text']
    if isEmpty(input_text):
      return "You said nothing!! What's up? Are you okay?"

    global help_agent
    ans = help_agent.get_help(input_text)
    answer = ans['answer']
    if isEmpty(answer):
      return "Sorry! I don't understand what you said. Can you ask other topics?"
    ans['answer'] = self.apply_context(ans['answer'])
    ans['timestamp'] = get_timestamp()
    
    if ans['probility'] < 0.2:
      message = json.dumps(ans)
      try:
        global agent_response_body, connection
        agent_response_body = None
        self.channel.basic_publish(exchange='',
                          routing_key='task_queue',
                          body=message,
                          properties=pika.BasicProperties(
                            delivery_mode = 2, # make message persistent
                          ))
        print("[x] Sending message to queue")
        count = 0
        while agent_response_body is None:
          connection.process_data_events()
          time.sleep(2)
          count = count + 1
          if count > 10:
            break

        if agent_response_body is None:
          ans['answer'] = "I'm sorry I do not know the answer to this at the moment. I will email a response to you within 24 hours."
          ans['agent_response'] = None
        else:
          ans['agent_response'] = agent_response_body
          ans['answer'] = agent_response_body
          output_file = open(os.path.join(CURR_PATH, data_filename), "a")
          output_file.write("\n%s||%s" % (ans['question'],  agent_response_body))
          output_file.close()
          help_agent = Glados()

        print("Agent response %s" % agent_response_body)

      except Exception as e:
        print(e)
    self.save(ans)
    return ans
    
  def save(self, orginal):
    response = orginal.copy()
    response['user_id'] = 0
    if 'user' in g and g.user is not None:
      response['user_id'] = g.user['id'] 
    self.bot_responses.save(response)
   
  def apply_context(self, text):
      return text % test_account_info 
    
