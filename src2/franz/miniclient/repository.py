import time, cjson
from request import *

def listCatalogs(serverURL):
    return jsonRequest(pycurl.Curl(), "GET", serverURL + "/catalogs")

def openCatalog(serverURL, catalog, user=None, password=None):
    return Catalog(serverURL + catalog, user, password)

class Catalog:
    def __init__(self, url, user=None, password=None):
        self.url = url
        self.curl = pycurl.Curl()
        if user and password: self.setAuth(user, password)

    def listTripleStores(self):
        """Returns the names of open stores on the server."""
        repos = jsonRequest(self.curl, "GET", self.url + "/repositories")
        return [repo["id"][1:-1].replace("\\\"", "\"").replace("\\\\", "\\") for repo in repos]

    def createTripleStore(self, name):
        """Ask the server to create a new triple store."""
        nullRequest(self.curl, "PUT", self.url + "/repositories/" + urllib.quote(name))

    def federateTripleStores(self, name, storeNames):
        """Create a federated store."""
        nullRequest(self.curl, "PUT", self.url + "/repositories/" + urllib.quote(name) +
                    "?" + urlenc(federate=storeNames))

    def deleteTripleStore(self, name):
        """Delete a server-side triple store."""
        nullRequest(self.curl, "DELETE", self.url + "/repositories/" + urllib.quote(name))

    def getRepository(self, name):
        """Create an access object for a triple store."""
        return Repository(self.curl, self.url + "/repositories/" + urllib.quote(name))

    def setAuth(self, user, password):
        """Set a username and password to use when talking to this server."""
        self.curl.setopt(pycurl.USERPWD, "%s:%s" % (user, password))
        self.curl.setopt(pycurl.HTTPAUTH, pycurl.HTTPAUTH_BASIC)


class Repository:
    def __init__(self, curl, url):
        # TODO verify existence of repository at this point?
        self.url = url
        self.curl = curl
        self.environment = None

    def getSize(self, context=None):
        """Returns the amount of triples in the repository."""
        return jsonRequest(self.curl, "GET", self.url + "/size", urlenc(context=context))

    def listContexts(self):
        """Lists the contexts (named graphs) that are present in this repository."""
        return [t["contextID"] for t in jsonRequest(self.curl, "GET", self.url + "/contexts")]

    def isWriteable(self):
        return jsonRequest(self.curl, "GET", self.url + "/writeable")

    def evalSparqlQuery(self, query, infer=False, context=None, namedContext=None, callback=None,
                        bindings=None):
        """Execute a SPARQL query. Context can be None or a list of
        contexts -- strings in "http://foo.com" form or "null" for the
        default context. Return type depends on the query type. ASK
        gives a boolean, SELECT a {names, values} object containing
        lists of lists of terms. CONSTRUCT and DESCRIBE return a list
        of lists representing statements. Callback WILL NOT work on
        ASK queries."""
        if (bindings is not None):
            bindings = [a + " " + b for a, b in bindings.items()]
        return jsonRequest(self.curl, "GET", self.url,
                           urlenc(query=query, infer=infer, context=context, namedContext=namedContext,
                                  environment=self.environment, bind=bindings),
                           rowreader=callback and RowReader(callback))

    def evalPrologQuery(self, query, infer=False, callback=None, limit=None):
        """Execute a Prolog query. Returns a {names, values} object."""
        return jsonRequest(self.curl, "POST", self.url,
                           urlenc(query=query, infer=infer, queryLn="prolog", environment=self.environment, limit=limit),
                           rowreader=callback and RowReader(callback))

    def definePrologFunctor(self, definition):
        nullRequest(self.curl, "PUT", self.url + "/functor?" + urlenc(environment=self.environment), definition)

    def getStatements(self, subj=None, pred=None, obj=None, context=None, infer=False, callback=None):
        """Retrieve all statements matching the given constraints.
        Context can be None or a list of contexts, as in
        evalSparqlQuery."""
        subjEnd, predEnd, objEnd = None, None, None
        if isinstance(subj, tuple): subj, subjEnd = subj
        if isinstance(pred, tuple): pred, predEnd = pred
        if isinstance(obj, tuple): obj, objEnd = obj
        ##print "OBJ", obj, "OBJEND", objEnd
        ##print "GET STATEMENTS '%s'" % context
        return jsonRequest(self.curl, "GET", self.url + "/statements",
                           urlenc(subj=subj, subjEnd=subjEnd, pred=pred, predEnd=predEnd,
                                  obj=obj, objEnd=objEnd, context=context, infer=infer),
                           rowreader=callback and RowReader(callback))

    def addStatement(self, subj, pred, obj, context=None):
        """Add a single statement to the repository."""
        ##print "ADD STATEMENT CONTEXT '%s' " % context, type(context)
        nullRequest(self.curl, "POST", self.url + "/statements", cjson.encode([[subj, pred, obj, context]]),
                    contentType="application/json")

    def deleteMatchingStatements(self, subj=None, pred=None, obj=None, context=None):
        """Delete all statements matching the constraints from the
        repository. Context can be None or a single graph name."""
        nullRequest(self.curl, "DELETE", self.url + "/statements",
                    urlenc(subj=subj, pred=pred, obj=obj, context=context))

    def addStatements(self, quads):
        """Add a collection of statements to the repository. Quads
        should be an array of four-element arrays, where the fourth
        element, the graph name, may be None."""
        nullRequest(self.curl, "POST", self.url + "/statements", cjson.encode(quads), contentType="application/json")

    class UnsupportedFormatError(Exception):
        def __init__(self, format):
            self.format = format
        def __str__(self):
            return "'%s' file format not supported (try 'ntriples' or 'rdf/xml')." % self.format

    def checkFormat(self, format):
        if format == "ntriples": return "text/plain"
        elif format == "rdf/xml": return "application/rdf+xml"
        else: raise Repository.UnsupportedFormatError(format)

    def loadData(self, data, format, baseURI=None, context=None):
        nullRequest(self.curl, "POST", self.url + "/statements?" + urlenc(context=context, baseURI=baseURI),
                    data.encode("utf-8"), contentType=self.checkFormat(format))

    def loadFile(self, file, format, baseURI=None, context=None, serverSide=False):
        mime = self.checkFormat(format)
        body = ""
        if not serverSide:
            f = open(file)
            body = f.read()
            f.close()
            file = None
        params = urlenc(file=file, context=context, baseURI=baseURI)
        nullRequest(self.curl, "POST", self.url + "/statements?" + params, body, contentType=mime)

    def getBlankNodes(self, amount=1):
        return jsonRequest(self.curl, "POST", self.url + "/blankNodes", urlenc(amount=amount))

    def deleteStatements(self, quads):
        """Delete a collection of statements from the repository."""
        nullRequest(self.curl, "POST", self.url + "/statements/delete", cjson.encode(quads), contentType="application/json")

    def listIndices(self):
        """List the SPOGI-indices that are active in the repository."""
        return jsonRequest(self.curl, "GET", self.url + "/indices")

    def addIndex(self, type):
        """Register a SPOGI index."""
        nullRequest(self.curl, "PUT", self.url + "/indices/" + type)

    def deleteIndex(self, type):
        """Drop a SPOGI index."""
        nullRequest(self.curl, "DELETE", self.url + "/indices/" + type)

    def getIndexCoverage(self):
        """Returns the proportion (0-1) of the repository that is indexed."""
        return jsonRequest(self.curl, "GET", self.url + "/indexing")

    def indexStatements(self, all=False):
        """Index any unindexed statements in the repository. If all is
        True, the whole repository is re-indexed."""
        nullRequest(self.curl, "POST", self.url + "/indexing", urlenc(all=all))

    def setIndexingTripleTreshold(self, size=None):
        nullRequest(self.curl, "PUT", self.url + "/indexing/tripleTreshold", "%d" % (size or 0),
                    contentType="text/plain")

    def setIndexingChunkTreshold(self, size=None):
        nullRequest(self.curl, "PUT", self.url + "/indexing/chunkTreshold", "%d" % (size or 0),
                    contentType="text/plain")

    def evalFreeTextSearch(self, pattern, infer=False, callback=None):
        """Use free-text indices to search for the given pattern.
        Returns an array of statements."""
        return jsonRequest(self.curl, "GET", self.url + "/freetext", urlenc(pattern=pattern, infer=infer),
                           rowreader=callback and RowReader(callback))

    def listFreeTextPredicates(self):
        """List the predicates that are used for free-text indexing."""
        return jsonRequest(self.curl, "GET", self.url + "/freetextPredicates")

    def registerFreeTextPredicate(self, predicate):
        """Add a predicate for free-text indexing."""
        nullRequest(self.curl, "POST", self.url + "/freetextPredicates", urlenc(predicate=predicate))

    def setEnvironment(self, name):
        """Repositories use a current environment, which are
        containers for namespaces and Prolog predicates. Every
        server-side repository has a default environment that is used
        when no environment is specified."""
        self.environment = name

    def listEnvironments(self):
        return jsonRequest(self.curl, "GET", self.url + "/environments")

    def createEnvironment(self, name=None):
        return jsonRequest(self.curl, "POST", self.url + "/environments", urlenc(name=name))

    def deleteEnvironment(self, name):
        nullRequest(self.curl, "DELETE", self.url + "/environments", urlenc(name=name))

    def listNamespaces(self):
        return jsonRequest(self.curl, "GET", self.url + "/namespaces", urlenc(environment=self.environment))

    def clearNamespaces(self):
        nullRequest(self.curl, "DELETE", self.url + "/namespaces?" + urlenc(environment=self.environment))

    def addNamespace(self, prefix, uri):
        nullRequest(self.curl, "PUT", self.url + "/namespaces/" + urllib.quote(prefix) + "?"
                    + urlenc(environment=self.environment), uri, contentType="text/plain")

    def deleteNamespace(self, prefix):
        nullRequest(self.curl, "DELETE", self.url + "/namespaces/" + urllib.quote(prefix) + "?"
                    + urlenc(environment=self.environment))

    def listMappedTypes(self):
        return jsonRequest(self.curl, "GET", self.url + "/typeMapping")

    def addMappedType(self, type, primitiveType):
        nullRequest(self.curl, "POST", self.url + "/typeMapping", urlenc(type=type, primitiveType=primitiveType))

    def deleteMappedType(self, type):
        nullRequest(self.curl, "DELETE", self.url + "/typeMapping", urlenc(type=type))

    def listMappedPredicates(self):
        return jsonRequest(self.curl, "GET", self.url + "/predicateMapping")

    def addMappedPredicate(self, predicate, primitiveType):
        nullRequest(self.curl, "POST", self.url + "/predicateMapping",
                    urlenc(predicate=predicate, primitiveType=primitiveType))

    def deleteMappedPredicate(self, predicate):
        nullRequest(self.curl, "DELETE", self.url + "/predicateMapping", urlenc(predicate=predicate))


######################################################
## TESTING CODE
######################################################

def timeQuery(rep, n, size):
    t = time.time()
    for i in range(n):
        rep.evalSparqlQuery("select ?x ?y ?z {?x ?y ?z} limit %d" % size)
    print "Did %d %d-row queries in %f seconds." % (n, size, time.time() - t)

def test0():
    cats = listCatalogs("http://localhost:8080")
    print "List of catalogs:", cats
    cat = openCatalog("http://localhost:8080", cats[0])
    print "Found cat", cat.url
    reps = cat.listTripleStores()
    print "Is 'test' there??:", reps, "test" in reps
    try:
        print "Creating repository 'test'"
        cat.createTripleStore("test")
        reps = cat.listTripleStores()
        print "Now is 'test' there??:", reps, "test" in reps
    except: pass
    rep = cat.getRepository("test")
    size = rep.getSize()
    print "Size of 'test' repository", size
    if size == 0:
        rep.addStatement('<http://www.franz.com/example#ted>', '<http://www.franz.com/example#age>', '"55"^^<http://www.w3.org/2001/XMLSchema#int>', "<http://foo.com>")
    query = """select ?x ?y ?z {?x ?y ?z} limit 5"""
    answer = rep.evalSparqlQuery(query, context="<http://foo.com>")
    print answer['names']
    for v in answer['values']:
        print v
    timeQuery(rep, 1000, 5)

def openRep (name="test"):
    server = "http://localhost:8080"
    cats = listCatalogs(server)
    print "List of catalogs:", cats
    cat = openCatalog(server, cats[0])
    print "Found cat", cat.url
    reps = cat.listTripleStores()
    print ("Is '%s' there??:" % name), reps, name in reps
    try:
        print "Creating repository '%s'" % name
        cat.createTripleStore(name)
        reps = cat.listTripleStores()
        print ("Now is '%s' there??:" % name), reps, name in reps
    except: pass
    rep = cat.getRepository(name)
    size = rep.getSize()
    print ("Size of '%s' repository" % name), size
    return rep

def makeTerm(term, is_literal=False):
    if is_literal:
        return "\"" + term.replace("\"", "\\\"") + "\""
    elif not term == None:
        return "<" + term + ">"
    else:
        return None

def makeStatement(subject, predicate, object, context=None, is_literal=False):
    return [makeTerm(subject), makeTerm(predicate), makeTerm(object, is_literal=is_literal),
            makeTerm(context)]

def test1():
    rep = openRep();
    print("Adding statements ...")
    ns = "http://example.org#"
    stmts = []
    stmts.append(makeStatement(ns + "alice", ns + "name", "alice", is_literal=True))
    stmts.append(makeStatement(ns + "bob", ns + "name", "bob", is_literal=True))
    rep.addStatements(stmts)
    print rep.listMappedTypes()
    rep.addMappedType("<http://foo.com/type>", "int")
    print rep.listMappedTypes()
    print "Repository size = ", rep.getSize()

if __name__ == '__main__':
    choice = 1
    print "Run test%i" % choice
    if choice == 0: test0()
    elif choice == 1: test1()
    elif choice == 2: test2()
    elif choice == 3: test3()
    elif choice == 4: test4()
