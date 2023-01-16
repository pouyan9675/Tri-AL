

def column(name):
    def inner(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        wrapper.column = name
        return wrapper
    return inner
