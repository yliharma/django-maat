from django.db.models.base import ModelBase
from django.contrib.contenttypes import generic

from .exceptions import ModelNotRegistered, ModelAlreadyRegistered
from .models import MaatRanking

def get_handler_instance(model, handler_class, options):
    """ Returns an handler instance for the given *model*. """
    handler = handler_class(model)
    for key, value in options.items():
        setattr(handler, key, value)
    return handler

def contribute_to_class(model):
    """
    Adds a 'maat_ranking' attribute to each instance of model.
    The attribute is a generic relation to MaatRanking, used by the
    handler to retrieve the ordered queryset.
    """
    generic_relation = generic.GenericRelation(MaatRanking)
    generic_relation.contribute_to_class(model, 'maat_ranking')


class MaatRegister(object):
    """
    Register class.
    """
    def __init__(self):
        self._registry = {}
    
    def get_handler_for_model(self, model):
        """
        Returns an handler for the given *model*. If the model has not been
        registered, it raises a *ModelNotRegistered* exception.
        """
        try:
            return self._registry[model]
        except KeyError:
            raise ModelNotRegistered('Model %s is not handled' % model)
    
    def get_registered_handlers(self):
        """ Returns a list of all the registered handlers. """
        return self._registry.values()
    
    def register(self, model_or_iterable, handler_class, **kwargs):
        """
        Registers a model or a list of models to be handled by *handler_class*.
        Once registered, a model gains a new attribute *maat* which can be
        used to retrieve an ordered queryset.
        
        Eg:
        
            from djangomaat.register import maat
            
            maat.register(Article, ArticleMaatHandler)
            
            ordered_article_list = Article.maat.ordered_by('popularity')
        
        Plus, the management command `populate_maat_ranking` will 
        automatically process the model.
        """
        if isinstance(model_or_iterable, ModelBase):
            model_or_iterable = [model_or_iterable]
        for model in model_or_iterable:
            if model in self._registry:
                raise ModelAlreadyRegistered(
                    "The model %s is already registered." % 
                    model._meta.module_name)
            handler = get_handler_instance(model, handler_class, kwargs)
            self._registry[model] = handler
            contribute_to_class(model)

    def unregister(self, model_or_iterable):
        """ Do not use it. Just for testing, really. """
        if isinstance(model_or_iterable, ModelBase):
            model_or_iterable = [model_or_iterable]
        for model in model_or_iterable:
            if model in self._registry:
                del self._registry[model]

maat = MaatRegister()