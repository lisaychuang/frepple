#!/usr/bin/python
#  file     : $URL$
#  revision : $LastChangedRevision$  $LastChangedBy$
#  date     : $LastChangedDate$
#  email    : jdetaeye@users.sourceforge.net

# This script is a simple, generic model generator. A number of different
# models are created with varying number of clusters, depth of the supply path
# and number of demands per cluster. By evaluating the runtime of these models
# we can evaluate different aspects of Frepple's scalability.
#
# This test script is meant more as a sample for your own tests on evaluating
# scalability.
#
# The autogenerated supply network looks schematically as follows:
#   [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
#   [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
#   [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
#   [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
#   [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
#       ...                                  ...
# Each row represents a cluster.
# The operation+buffer are repeated as many times as the depth of the supply
# path parameter.
# In each cluster a single item is defined, and a parametrizable number of
# demands is placed on the cluster.


from freppledb.input.models import *
import time, os, os.path, sys, random
from datetime import timedelta, datetime
from django.db import connection
from django.db import transaction
from django.core.cache import cache
from django.conf import settings


# This function generates a random date
startdate = datetime(2007,1,1)
def getDate():
  global startdate
  return startdate + timedelta(random.uniform(0,365))


@transaction.commit_manually
def erase_model():
  '''
  This routine erase all model data from the database.
  '''
  cursor = connection.cursor()
  if settings.DATABASE_ENGINE in ['sqlite3','postgresql_psycopg2']:
    cursor.execute('PRAGMA synchronous = OFF')
    delete = "delete from %s"
  else:
    delete = "truncate table %s"
  for table in [
    'out_problem','out_flowplan','out_loadplan','out_operationplan',
    'dates','demand','forecastdemand','forecast','flow','resourceload','buffer',
    'resource','operationplan','item','suboperation','operation','location',
    'bucket','calendar','customer'
    ]:
    cursor.execute(delete % table)
    transaction.commit()
  if settings.DATABASE_ENGINE == 'sqlite3':
    # Shrink the database file
    cursor.execute('vacuum')


@transaction.commit_manually
def createDates():
  global startdate

  # Performance improvement for sqlite during the bulky creation transactions
  if settings.DATABASE_ENGINE == 'sqlite3':
    connection.cursor().execute('PRAGMA synchronous=OFF')

  try:
    for i in range(365):
      # Loop through 1 year of daily buckets
      curdate = startdate + timedelta(i)
      month = int(curdate.strftime("%m"))  # an integer in the range 1 - 12
      quarter = (month-1) / 3 + 1          # an integer in the range 1 - 4
      year = int(curdate.strftime("%Y"))
      dayofweek = int(curdate.strftime("%w")) # day of the week, 0 = sunday, 1 = monday, ...
      d = Dates(
        day = curdate,
        dayofweek = dayofweek,
        week = curdate.strftime("%Y W%W"),     # Weeks are starting on monday
        week_start = curdate - timedelta((dayofweek+6)%7),
        week_end = curdate - timedelta((dayofweek+6)%7-7),
        month =  curdate.strftime("%b %Y"),
        month_start = date(year, month, 1),
        month_end = date(year+month/12, month+1-12*(month/12), 1),
        quarter = str(year) + " Q" + str(quarter),
        quarter_start = date(year, quarter*3-2, 1),
        quarter_end = date(year+quarter/4, quarter*3+1-12*(quarter/4), 1),
        year = curdate.strftime("%Y"),
        year_start = date(year,1,1),
        year_end = date(year+1,1,1),
        )
      d.save()
  finally:
    transaction.commit()


@transaction.commit_manually
def create_model (cluster, demand, level, resource, utilization):
  '''
  This routine populates the database with a sample dataset.
  '''
  # Initialization
  global startdate
  random.seed(100) # Initialize random seed to get reproducible results
  cnt = 100000     # a counter for operationplan identifiers

  # Performance improvement for sqlite during the bulky creation transactions
  if settings.DATABASE_ENGINE == 'sqlite3':
    connection.cursor().execute('PRAGMA synchronous=OFF')

  try:
    # Dates
    print "Creating dates..."
    createDates()

    # Plan start date
    print "Creating plan..."
    try:
      p = Plan.objects.all()[0]
      p.currentdate = startdate
      p.save()
    except:
      # No plan exists yet
      p = Plan(name="frepple", current=startdate)
      p.save()

    # Create a random list of categories to choose from
    categories = [ 'cat A','cat B','cat C','cat D','cat E','cat F','cat G' ]

    # Create customers
    print "Creating customers..."
    cust = []
    for i in range(100):
      c = Customer(name = 'Cust %03d' % i)
      cust.append(c)
      c.save()
    transaction.commit()

    # Calculate the average duration for loading a resource, based on the
    # following equations:
    #   Total available capacity = Number of resources
    #                              * 365 (ie total time)
    #                              * resource capacity
    #   Total capacity need = Number of items
    #                         * number of demands per item
    #                         * 1 (ie resource load per unit of demand)
    #                         * 5.5 (ie average units per demand)
    #   Utilization = Total capacity need / Total available capacity
    capacity = float(cluster * demand * 550) / (resource * 365 * utilization)
    capacity = int(capacity)+1

    # Create resources and their calendars
    print "Creating resources and calendars..."
    res = []
    for i in range(resource):
      cal = Calendar(name='capacity for res %03d' %i, category='capacity')
      bkt = Bucket(startdate=startdate, value=capacity, calendar=cal)
      cal.save()
      bkt.save()
      r = Resource(name = 'Res %03d' % i, maximum=cal)
      res.append(r)
      r.save()
    transaction.commit()

    # Loop over all clusters
    durations = [ 0, 0, 0, 86400, 86400*2, 86400*3, 86400*5, 86400*6 ]
    for i in range(cluster):
      print "Creating cluster %d..." % i

      # location
      loc = Location.objects.create(name='Loc %05d' % i)

      # Item and delivery operation
      oper = Operation.objects.create(name='Del %05d' % i, sizemultiple=1)
      it = Item.objects.create(name='Itm %05d' % i, operation=oper, category=random.choice(categories))

      # Level 0 buffer
      buf = Buffer.objects.create(name='Buf %05d L00' % i,
        item=it,
        location=loc,
        category='00'
        )
      fl = Flow.objects.create(operation=oper, thebuffer=buf, quantity=-1)

      # Demand
      total_demand = 0
      for j in range(demand):
        dm = Demand(name='Dmd %05d %05d' % (i,j),
          item=it,
          quantity=int(random.uniform(1,11)),
          due=getDate(),
          priority=int(random.uniform(1,4)),
          customer=random.choice(cust),
          category=random.choice(categories)
          )
        total_demand += dm.quantity
        dm.save()

      # Upstream operations and buffers
      for k in range(level):
        if k == 1 and res:
          # Create a resource load for operations on level 1
          oper = Operation(name='Oper %05d L%02d' % (i,k),
            type='OPERATION_TIME_PER',
            duration_per=86400,
            sizemultiple=1,
            )
          oper.save()
          ld = Load(resource=random.choice(res), operation=oper)
          ld.save()
        else:
          oper = Operation(name='Oper %05d L%02d' % (i,k),
            duration=random.choice(durations),
            sizemultiple=1,
            )
          oper.save()
        buf.producing = oper
        fl = Flow(operation=oper, thebuffer=buf, quantity=1, type="FLOW_END")
        buf.save()
        fl.save()
        buf = Buffer(name='Buf %05d L%02d' % (i,k+1),
          item=it,
          location=loc,
          category='%02d' % (k+1)
          )
        # Some inventory in random buffers
        if random.uniform(0,1) > 0.8: buf.onhand=int(random.uniform(5,20))
        fl = Flow(operation=oper, thebuffer=buf, quantity=-1)
        buf.save()
        fl.save()

      # Create supply operation
      oper = Operation(name='Sup %05d' % i, sizemultiple=1)
      fl = Flow(operation=oper, thebuffer=buf, quantity=1)
      oper.save()
      fl.save()

      # Create actual supply
      while total_demand > 0:
          cnt += 1
          arrivaldate = getDate()
          opplan = OperationPlan(identifier=cnt, operation=oper, quantity=int(random.uniform(1,100)), startdate=arrivaldate, enddate=arrivaldate)
          total_demand -= opplan.quantity
          opplan.save()

      # Commit the current cluster
      transaction.commit()

  finally:
    # Commit it all, even in case of exceptions
    transaction.commit()
