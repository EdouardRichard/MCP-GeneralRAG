class SalienceService:
    def __init__(self, beta=0.05, gamma=1.0):
        self.beta, self.gamma = beta, gamma

    def initial(self):
        return 0.0

    def update(self, salience, *, access_count, age_days):
        return max(0.0, salience * (1 - self.beta * age_days) + self.gamma * access_count)

    def rank_signal(self, salience, *, decay_rate):
        return salience if decay_rate > 0 else 0.0
