class SalienceService:
    def __init__(self, beta=0.05, gamma=1.0):
        self.beta, self.gamma = beta, gamma

    def initial(self):
        return 0.0

    def update(self, salience, *, access_count, age_days):
        return max(0.0, salience - self.beta * max(0., age_days) + self.gamma * access_count)

    def rank_signal(self, salience, *, decay_rate, age_days=None):
        if decay_rate <= 0 or age_days is None:
            return 0.0
        return max(0.0, salience - decay_rate * max(0., age_days))
