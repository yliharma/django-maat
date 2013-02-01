import inspect
import dse
from time import time

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import MaatRanking
from .exceptions import ManagerDoesNotExist, TypologyNotImplemented
from .utils import auto_increment

GETTER_PREFIX = 'get_pk_list_for_'

class MaatHandler(object):
    """
    Abstract class that manages the creation and the retrieving of ordered
    subsets of querysets for a given model.
    These querysets are handled by subclasses by implementing one or more
    'get_pk_list_for_[typology_name]' methods that should return a list of
    ids ordered the way they are expected to be retrieved.
    The typology_name is then used to retrieve the objects through the handler
    *ordered_by* method.
    
    Eg:
    
        from djangomaat.register import maat
        from djangomaat.handlers import MaatHandler
    
        class ArticleMaatHanlder(MaatHandler):
            
            def get_pk_list_for_popularity(self):
                return [i[0] for i in Article.objects.filter(
                    popularity__content_type=ContentType.objects.get_for_model(Article),
                ).order_by('-popularity__score').values_list('pk')[:1000]]
    
        maat.register(Article, ArticleMaatHanlder)
    
    The handler will monkey patch the associated model class by adding a 
    *maat* attribute that can be used to retrieve the ordered objects:
    
    Eg:
    
        ordered_article_list = Article.maat.ordered_by('popularity')
    
    If you need to retrieve the objects in inverted order, simply prefix the 
    minus sign to the typology argument:
    
    Eg:
    
        inverted_article_list = Article.maat.ordered_by('-popularity')
    
    When retrieving objects, djangomaat will use the default manager for the
    model, but it can be overwritten by specifying the name of a custom one
    through the *manager* attribute. If the *manager* cannot be found, a
    ManagerDoesNotExist exception will be raised:
    
    Eg:
    
        ...
        class ArticleMaatHanlder(MaatHandler):
            manager = 'published_objects'
            ...
    
    Being that the *ordered_by* return value is a plain Django queryset, it
    can be sliced, filtered etc. 
    """
    manager = '_default_manager'
    
    def __init__(self, model_class):
        self.model_class = model_class
        setattr(self.model_class, 'maat', HandlerDescriptor(self))
    
    def __unicode__(self):
        ct = self._get_content_type()
        return u'%s.%s' % (ct.app_label, ct.model)
    
    def _get_model_manager(self):
        """
        Returns the model manager that should be used when retrieving objects
        through the *ordered_by* method.
        """
        if not hasattr(self.model_class, self.manager):
            raise ManagerDoesNotExist("Model %s doesn't have a manager %s" % (
                                      self.model_class, self.manager))
        return getattr(self.model_class, self.manager)
    
    def _get_valid_typologies(self):
        """ Returns a list with the implemented typologies for this handler. """
        if not hasattr(self, '_valid_typologies'):
            self._valid_typologies = [i[0] for i in self._typology_getters_iterator()]
        return self._valid_typologies
    
    def _validate_typology(self, typology):
        """ Raises an excpetion if the typology passed in is not implemented. """
        if not typology in self._get_valid_typologies():
            raise TypologyNotImplemented("Typology %s not implemented" % typology)
    
    def _typology_getters_iterator(self):
        """
        Through introspection, returns an iterator over a list of tuples like
            [(typology_name_1, method_1),
             (typology_name_2, method_2)]
        where method name starts with GETTER_PREFIX.
        """
        getter_prefix_length = len(GETTER_PREFIX)
        return ((k[getter_prefix_length:], v)
            for k, v in inspect.getmembers(self, predicate=inspect.ismethod)
            if k.startswith(GETTER_PREFIX))
    
    def _get_content_type(self):
        """
        Caches and returns the content type of the model this handler is
        attached to.
        """
        if not hasattr(self, '_content_type'):
            self._content_type = ContentType.objects.get_for_model(self.model_class)
        return self._content_type
    
    def flush_ordered_objects(self, logger=None, simulate=False):
        """
        Replaces all the current rankings for the model this handler is
        attached to.
        This method gets called by the management command.
        """
        if logger:
            if simulate:
                logger.write('Simulating flushing...\n')
            else:
                logger.write('Flushing...\n')
            
        dse.patch_models(specific_models=[MaatRanking])
        for typology, getter in self._typology_getters_iterator():

            if logger:
                logger.write(u'Handler: %s - Typology: %s\n' % (self, typology))
            
            if not simulate:
                with transaction.commit_on_success():
                    # First, insert the new values, all set as not usable
                    with MaatRanking.delayed as d:
                        if logger:
                            logger.write('Insert...')
                            start = time()
                        
                        current_position = auto_increment(1)
                        for object_id in getter():
                            d.insert(dict(
                                content_type_id=self._get_content_type().pk,
                                object_id=object_id,
                                typology=typology,
                                usable=False,
                                position=current_position.next()
                            ))
                        if logger:
                            end = time()
                            duration = end - start
                            logger.write(' done (%.3f sec)\n' % duration)
                    
                    # ...then delete the old values...
                    with MaatRanking.delayed as d:
                        if logger:
                            logger.write('Delete...')
                            start = time()
                        for rank in MaatRanking.objects.filter(
                            content_type=self._get_content_type(), 
                            typology=typology,
                            usable=True).values('id'):
                            d.delete(int(rank.get('id')))
                        if logger:
                            end = time()
                            duration = end - start
                            logger.write(' done (%.3f sec)\n' % duration)
                    
                    # ...and lastly update the inserted values as usable
                    with MaatRanking.delayed as d:
                        if logger:
                            logger.write('Update...')
                            start = time()
                        for rank in MaatRanking.objects.filter(
                            content_type=self._get_content_type(), 
                            typology=typology,
                            usable=False).values('id'):
                            d.update(dict(id=rank.get('id'), usable=True))
                        if logger:
                            end = time()
                            duration = end - start
                            logger.write(' done (%.3f sec)\n' % duration)
    
    def ordered_by(self, typology):
        """
        Returns the queryset ordered by position relatively to the *typology*.
        The default ordering is ASC, but it can be inverted by prefixing
        *typology* with a minus sign.
        
        Eg:
        
            ordered_article_list = Article.maat.ordered_by('popularity')
        
        If the given *typology* has not been implemented through a 
        get_pk_list_for_[typology] method, it will raise a 
        TypologyNotImplemented exception.
        """
        ordering_prefix = ''
        if typology.startswith('-'):
            typology = typology[1:]
            ordering_prefix = '-'
        self._validate_typology(typology)
        return self._get_model_manager().filter(
            maat_ranking__content_type=self._get_content_type(),
            maat_ranking__typology=typology,
            maat_ranking__usable=True
        ).order_by('%smaat_ranking__position' % ordering_prefix)
    

class HandlerDescriptor(object):
    """ Makes the handle accessible only by the class, not its instances. """
    def __init__(self, handler):
        self.handler = handler
    
    def __get__(self, instance, type=None):
        if instance != None:
            raise AttributeError("Handler isn't accessible via %s instances" % type.__name__)
        return self.handler
    
