class BaseHandler:
    def __init__(self, app):
        self.app = app

    def register(self):
        raise NotImplementedError("Реализуй метод register() в подклассе")
