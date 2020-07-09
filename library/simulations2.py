import time
from library.local_environments import agent_environment, orderbook_environment
import numpy as np
from matplotlib import pyplot as plt
import random
import wandb


class simulator:

	def __init__(self,market_,agent, params = None, test_name = 'undefined',orderbook = False):
		
		# Default params
		if params is None:
			params = params = {"terminal" : 1, "num_trades" : 50, "position" : 10, "batch_size" : 32,"action_values" : [0,0.001,0.005,0.01,0.02,0.05,0.1] }
			print("Initialising using default parameters")

		self.terminal = params["terminal"]
		self.num_steps = params["num_trades"]
		self.batch_size = params["batch_size"]
		self.agent = agent

		self.m = market_
		self.possible_actions = params["action_values"]
		if orderbook:
			self.env = orderbook_environment(self.m,
								 params["position"],
								 params["num_trades"],
								 self.possible_actions
								)
		else:
			self.env = agent_environment(self.m,
								 params["position"],
								 params["num_trades"],
								 self.possible_actions
								)
		
		# TAG: Depreciate?
		self.intensive_training = False

		self.test_name = test_name

		# TAG: Depreciate?
		# Stats
		'''
		self.train_rewards = np.zeros((0,self.n_agents))
		self.eval_rewards = np.zeros((1,self.n_agents)) 
		self.eval_rewards_mean = np.zeros((0,self.n_agents)) 
		self.plot_title = "Unlabelled Performance Test"
		'''
		# TAG: Partially Depreciate?
		# Record actions
		'''
		self.train_actions = np.zeros((0,len(self.possible_actions),self.n_agents))
		self.episode_actions = np.zeros((len(self.possible_actions),self.n_agents))
		self.record_frequency = 500
		self.action_record_frequency = 100
		self.plot_y_lim = (0.96,0.99)
		self.episode_n = 0
		'''

		self.eval_freq = 500
		self.train_stat_freq = 100
		self.eval_window = 25
		self.episode_n = 0 # Number of training episodes completed

		self.logging_options = set(["count","value","position","event","reward"])
		# Try replacing below with logging matplotlib
		#self.position_granularity = 4

		# Wandb initialise and congigure
		self.new_run = wandb.init(project="OptEx",name = self.agent.agent_name,group = self.test_name,reinit=True)
		self.new_run.config.update({"num_trades": self.num_steps,
		 "batch_size": self.batch_size,
		 "action_size": len(self.possible_actions),
		 "state_size": self.env.state_size,
		 "temp_impact": self.env.m.k,
		 "perm_impact": self.env.m.b,
		 "stock": type(self.env.m.stock).__name__,
		 "orderbook": orderbook
		 })
		if self.agent.agent_type != "basic":
			self.new_run.config.update({"target_lag": self.agent.C,
			 "alt_target": self.agent.alternative_target,
		 	 "tree_horizon": self.agent.tree_n,
		 	 "buffer_size": self.agent.replay_buffer_size,
		 	 "learning_rate": self.agent.learning_rate,
		 	 "reward_scaling": self.agent.reward_scaling,
		 	 "action_input" : self.agent.action_as_input
		 	})
			
		if self.agent.agent_type == "dist":
			self.new_run.config.update({"twap_scaling": self.agent.twap_scaling})
			if type(agent).__name__ == "C51Agent":
				self.new_run.config.update({"support_range": self.agent.V_max - self.agent.V_min})
			if type(agent).__name__ == "QRAgent":
				self.new_run.config.update({"n_quantiles": self.agent.N})
			if self.agent.UCB:
				self.new_run.config.update({"UCBc": self.agent.c})
			else:
				self.new_run.config.update({"epsilon_min": self.agent.epsilon_min})
				self.new_run.config.update({"epsilon_decay": self.agent.epsilon_decay})
		else:
			self.new_run.config.update({"epsilon_min": self.agent.epsilon_min})
			self.new_run.config.update({"epsilon_decay": self.agent.epsilon_decay})

	@staticmethod
	def _moving_average(a, n=300):
		ret = np.cumsum(a, dtype=float)
		ret[n:] = ret[n:] - ret[:-n]
		return ret[n - 1:] / n

	def _pretrain_position(self):
		t = random.uniform(-1,1)
		a = random.randrange(len(self.possible_actions))
		state = [-1,t]
		next_time = max(1,t + 2 / self.num_steps)
		next_state = [-1,next_time]
		state = np.reshape(state, [1, self.env.state_size])
		next_state = np.reshape(next_state, [1, self.env.state_size])
		self.agent.remember(state, a, 0, next_state, True)

	# TAG: overhaul
	def pretrain(self,n_samples = 2000,n_iterations = 500):
		pretain_position = True
		pretrain_time = False
		for i in range(n_samples):
			## Pretrain for state where position is 0 ##
			
			# Randomly sample transformed t in the time interval [-1,1] and action from space
			if pretain_position:
				self._pretrain_position()

			## Pretrain for state where time is 0 ##
			if pretrain_time:
				# Randomly sample transformed position in the time interval [-1,1] and action from space
				p = random.uniform(-1,1)
				a = random.randrange(len(self.possible_actions))
				state = [p,1]
				state = np.reshape(state, [1, self.env.state_size])
				self.agent.remember(state, a, 0, state, True)

		for i in range(n_iterations):
			self.agent.replay(self.batch_size)

		# Clear the memory
		self.agent.memory.clear()
		print("Pretraining Complete")

	def _train(self,n_episodes):
		self.agent.evaluate = False
		for e in range(n_episodes):
			if e % self.train_stat_freq == 0:
				track = self.episode(evaluate = False,record = ["count","value"])
				for j in range(len(self.possible_actions)):
					self.new_run.log({'episode': self.episode_n, ('act_count' + str(j)): track["count"].count(j)})
			else:
				self.episode(evaluate = False)
			
			self.episode_n += 1


	def _evaluate(self,n_episodes):
		self.agent.evaluate = True
		total_count = []
		total_reward = 0
		total_position = [0] * self.num_steps
		for e in range(n_episodes):
			track = self.episode(evaluate = False,record = ["count","reward","position"])
			total_count += track["count"]
			total_reward += track["reward"]
			#print("position ",total_position,track["position"])
			total_position = [total_position[i] + (track["position"][i] if i < len(track["position"]) else 0) for i in range(self.num_steps)]

		for j in range(len(self.possible_actions)):
			self.new_run.log({'episode': self.episode_n, ('eval_act_count' + str(j)): track["count"].count(j) / n_episodes})
		self.new_run.log({'episode': self.episode_n, 'eval_rewards': total_reward / n_episodes})
		plt.bar(np.arange(self.num_steps) ,np.array(total_position) / n_episodes)
		plt.ylabel("Position")
		#print(np.arange(self.num_steps) / self.num_steps,np.array(total_position) / n_episodes)
		self.new_run.log({'episode': self.episode_n, 'position': plt})
	
	def train(self,n_episodes = 10000, epsilon = None, epsilon_decay = None,show_details = True, evaluate = False):
		
		# Default training parameters if not provided
		if epsilon is not None:
			self.agent.epsilon = epsilon

		if epsilon_decay is not None:
			self.agent.epsilon_decay = epsilon_decay

		# TAG: Deprecate
		# Setup action list
		action = -1

		# TAG: Deprecate
		agent_reward_dists = []
		initial_episode = self.episode_n
		while self.episode_n - initial_episode < n_episodes:
			self._train(self.eval_freq)
			self._evaluate(self.eval_window)
		
		# TAG: Depreciated
		'''
		for e in range(n_episodes): # iterate over new episodes of the game
			
			### Record Probabilities 4 times throughout training ###
			# Currently only record for the first dist agent
			if e % n_episodes / 5 == 0 and e>0:
				for agent in self.agents:
					if agent.agent_type == "dist":
						self.dist_agent_for_plot = agent
						init_state = [1,-1] 
						init_state = np.reshape(init_, [1, 2])
						agent_reward_dists.append(agent.probs(init_state))
						break
			
			self.episode(evaluate = evaluate)
			if not self.intensive_training:
				for i, agent in enumerate(self.agents):
					if len(agent.memory) > self.batch_size and not evaluate:
						agent.replay(self.batch_size) # train the agent by replaying the experiences of the episode
						agent.step() # Update target network if required


			if e % self.record_frequency == 0 and e>0:
				#self.total_training_steps += 100
				if show_details and not evaluate:
					current_training_step = len(self.eval_rewards_mean) # CHANGED TO EVAL
					self.evaluate(self.eval_window,show_stats=False)
					#ax.clear()
					#print(self.eval_rewards_mean)
					
					for i in range(self.eval_rewards_mean.shape[1]):
						self.wandb_agents[i].log({'episode': self.eval_rewards_mean.shape[0] * self.record_frequency, 'eval_rewards': self.eval_rewards_mean[-1,i]})
						#y_vals = self._moving_average(self.eval_rewards_mean[:,i],n=3)
						#x_vals = np.arange(len(y_vals)) * self.record_frequency
						#agent_label = self.agents[i].agent_name + "(" + str(round(self.agents[i].epsilon,3)) + ")"
						#ax.plot(x_vals,y_vals, label  = agent_label )
					#plt.legend()
					#plt.ylim(self.plot_y_lim) # Temporary
					#plt.title(self.plot_title)
					#plt.grid(b=True, which='major', axis='both')
					### TEMPORARY ###
					#twap_stat = 9.849
					#if len(x_vals) > 0:
						#plt.plot([0, x_vals[-1]], [twap_stat, twap_stat], 'k--')
					### TEMPORARY ###
					#plt.pause(0.0001)
					#plt.draw()
		if not evaluate:
			#self.show_stats(trained_from = current_training_step) 
			#for i, d in enumerate(agent_reward_dists):
				#self.show_dist(self.dist_agent_for_plot,d,figure = i + 1)
			wandb.join()
		else:
			self.eval_rewards_mean = np.vstack((self.eval_rewards_mean,self.eval_rewards / self.eval_window))
			self.eval_rewards = np.zeros((1,self.n_agents))
		'''
	def episode(self, verbose = False,evaluate = False, record = None):
		recording = record is not None and len(record) > 0
		if recording:	
			assert set(record).issubset(self.logging_options), "Undefined recording parameters"
		
		state = self.env.reset(training = (not evaluate)) # reset state at start of each new episode of the game

		# TAG: Depreciate
		#track_action_p = False
		
		track = {}
		if recording:
			# Log action values at t=0
			if "value" in record:
				for j in range(len(self.possible_actions)):
					predicts = self.agent.predict(state)[0]
					self.new_run.log({'episode': self.episode_n, ('act_val' + str(j)): predicts[j]})

			for stat in record:
				if not stat == "value" and not stat == "reward":
					track[stat] = []
				if stat == "reward":
					track[stat] = 0
			


		# TAG: Depreciate
		'''
		if not evaluate:
			self.episode_n += 1
			if self.episode_n % self.action_record_frequency == 0:
				track_action_p = True
				action_tracker = []
				for i, agent in enumerate(self.agents):
					for j in range(len(self.possible_actions)):
						predicts = agent.predict(state)[0]
						self.wandb_agents[i].log({'episode': self.episode_n, ('act_val' + str(j)): predicts[j]})
			#self.train_actions = np.concatenate((self.train_actions,[self.episode_actions]))
		else:
		'''
		
		done = False # Has the episode finished
		
		# TAG: Depreciated
		#inactive = False # Agents which are still trading
		

		for t in range(self.num_steps):
			# Get actions for each agent
			
			# Agents action only updated if still active
			#if not inactive:
			action = self.agent.act(state)
			#else:
			#action = -1 # Could speed up (only need to change once)
			
			next_state, reward, done = self.env.step(action)

			if recording:
				if "count" in record:
					track["count"].append(action)
				
				if "reward" in record:
					track["reward"] += reward

				if "event" in record:
					print("WARNING: Track events has not been implemented")
					track_events = False

				if "position" in record:
					track["position"].append(self.env.position)

			if not evaluate:
				self.agent.remember(state, action, reward, next_state, done)

			if verbose:
				print("Predict", self.agents[0].predict(state))
				print("State: ",state, "Actions: ", action, "Rewards: ", reward, "Next_states: ", next_state, "Done: ", done)
				# For final step print the predicted rewards for 0 position
				if t == self.num_steps - 1:
					print("Next predict", self.agents[0].predict(next_state))
			
			state = next_state
				
			if done: 
				break # exit loop
			
			# TAG: Depreciate?
			if self.intensive_training:
				for i, agent in enumerate(self.agents):
					if len(agent.memory) > self.batch_size and not evaluate:
						agent.replay(self.batch_size) # train the agent by replaying the experiences of the episode
						agent.step() # Update target network if required

		if not done:
			print(state)
			print("We have a problem.")
		
		return track

	def evaluate(self,n_episodes = 200,show_stats = True):
		assert False, "This function has not been updated to version 2"
		self.train(n_episodes = n_episodes, show_details = False,evaluate = True)
		# Return agent epsilons to their original values:
		for i, agent in enumerate(self.agents):
			agent.evaluate = False

		if show_stats:
			start_iteration = len(self.eval_rewards)
			self.show_stats(trained_from = start_iteration,training = False)

	def show_stats(self,trained_from = 0,trained_to = None,moving_average = 400,training = True):
		
		if training:
			if trained_to is None:
				trained_to = len(self.train_rewards)
			for i in range(self.train_rewards.shape[1]):
				plt.plot(self._moving_average(self.train_rewards[trained_from:trained_to,i],n=moving_average), label  = self.agents[i].agent_name)
		else:
			if trained_to is None:
				trained_to = len(self.eval_rewards)
			for i in range(self.eval_rewards.shape[1]):
				plt.plot(self._moving_average(self.eval_rewards[trained_from:trained_to,i],n=moving_average), label  = self.agents[i].agent_name)
		plt.legend()

	def show_dist(self, dist_agent, data,figure = 1, actions = [5,6]):
		plt.figure(figure)
		for a in actions:
			plt.bar(dist_agent.z,data[a][0],alpha = 0.4,width = 0.25,label = f"action {bar_act}")
		plt.legend()
		
	#def test_convergence(self,)

	def execute(self,agent):
		# Currently just one strat
		position = []
		cash = []
		states = self.env.reset() # reset state at start of each new episode of the game
		states = np.reshape(states, [len(training_agents),1, self.env.state_size])
			
		for t in range(self.num_steps):

			action = agent.act(states)
			next_state, reward, done = self.env.step(action)
			next_states = np.reshape(next_states, [len(training_agents),1, self.env.state_size])
			total_reward += rewards
			#print(total_reward)
			for i, agent in enumerate(training_agents):
				# Note this happens when its been done for more than one step
				training_agents[agent].remember(states[i], actions[i], rewards[i], next_states[i], done[i])
			states = next_states

			if all(done): 
				break 

		
		