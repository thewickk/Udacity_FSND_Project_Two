import random
import string
import httplib2
import json
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, \
    jsonify
from flask_bootstrap import Bootstrap
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Category, CategoryItem, User
from flask import session as login_session
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
from flask import make_response


app = Flask(__name__)
Bootstrap(app)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Udacity FSND Catalog Project"

engine = create_engine('sqlite:///database.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create a state token to prevent request forgery.
# Store it in the session for later validation.
@app.route('/login')
def showLogin():
    # Convert Python2 xrange() to Python3 range()
    xrange = range
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print("Token's client ID does not match app's.")
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'),
            200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one:
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: ' \
              '150px;-webkit-border-radius:\
               150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print("done!")
    return output


# User Helper Functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
        'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except Exception:
        return None


# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print('Access Token is None')
        response = make_response(json.dumps(
            'Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print('In gdisconnect access token is %s', access_token)
    print('User name is: ')
    print(login_session['username'])
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % \
          login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print('result is ')
    print(result)
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        flash("Successfully logged out!")
        return redirect(url_for('categories_home'))
        # return response
    else:
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# Making an API Endpoint for the Category Items:
# ALLOW PUBLIC ACCESS
@app.route('/<int:category_id>/JSON/')
def category_items_json(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    items = session.query(CategoryItem).filter_by(category_id=category_id)
    return jsonify(CategoryItem=[i.serialize for i in items])


# Making an API Endpoint for ONE Category Item:
# ALLOW PUBLIC ACCESS
@app.route('/<int:category_id>/<int:item_id>/JSON/')
def category_item_json(category_id, item_id):
    item = session.query(CategoryItem).filter_by(id=category_id).one()
    return jsonify(CategorItem=item.serialize)


# Home page to list all of our Categories:
# ALLOW PUBLIC ACCESS
@app.route('/')
def categories_home():
    category = session.query(Category).all()
    items = session.query(CategoryItem).order_by(CategoryItem.id.desc()).limit(
        5)
    return render_template('catalog.html', category=category, items=items)


# Page to add a new category to the app:
# RESTRICT TO LOGGED IN USERS ONLY
@app.route('/new/', methods=['GET', 'POST'])
def new_category():
    if 'username' not in login_session:
        return redirect('login')
    if request.method == 'POST':
        newCategory = Category(name=request.form['name'],
                               user_id=login_session['user_id'])
        session.add(newCategory)
        session.commit
        flash("new category created!")
        return redirect(url_for('categories_home'))
    else:
        return render_template('newCategory.html')


# Page to edit a category:
# RESTRICT TO LOGGED IN USERS ONLY
@app.route('/<int:category_id>/edit/', methods=['GET', 'POST'])
def edit_category(category_id):
    updatedCategory = session.query(Category).filter_by(id=category_id).one()
    if 'username' not in login_session:
        return redirect('login')
    if request.method == 'POST':
        if request.form['name']:
            updatedCategory.name = request.form['name']
        session.add(updatedCategory)
        session.commit()
        flash("category updated!")
        return redirect(url_for('categories_home'))
    else:
        return render_template('editCategory.html', category=updatedCategory)
        # category=updatedCategory is the database category at id=category_id
        # i.e. updatedCategory.name would = Baseball for example


# #Page to delete a category:
# RESTRICT TO LOGGED IN USERS ONLY
@app.route('/<int:category_id>/delete/', methods=['GET', 'POST'])
def delete_category(category_id):
    deleteCategory = session.query(Category).filter_by(id=category_id).one()
    if 'username' not in login_session:
        return redirect('login')
    if request.method == 'POST':
        session.delete(deleteCategory)
        session.commit()
        flash("category deleted!")
        return redirect(url_for('categories_home'))
    else:
        return render_template('deleteCategory.html', category=deleteCategory)


# Page to show a category and all of its associated items:
# ALLOW PUBLIC ACCESS
@app.route('/<int:category_id>/')
def category_items(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    items = session.query(CategoryItem).filter_by(category_id=category_id)
    return render_template('category.html', category=category, items=items)


# Page to add a new item to a specific category
# RESTRICT TO LOGGED IN USERS ONLY
@app.route('/<int:category_id>/new/', methods=['GET', 'POST'])
def new_category_item(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    if 'username' not in login_session:
        return redirect('login')
    if request.method == 'POST':
        newItem = CategoryItem(name=request.form['name'],
                               user_id=login_session['user_id'],
                               category_id=category_id)
        session.add(newItem)
        session.commit()
        flash("new category item created!")
        return redirect(url_for('category_items', category_id=category_id))
    else:
        return render_template('newItem.html', category=category,
                               category_id=category_id)


# Create route to edit a menu items:
# RESTRICT TO LOGGED IN USERS ONLY
@app.route('/<int:category_id>/<int:item_id>/edit/', methods=['GET', 'POST'])
def edit_category_item(category_id, item_id):
    updatedItem = session.query(CategoryItem).filter_by(id=item_id).one()
    if 'username' not in login_session:
        return redirect('login')
    if request.method == 'POST':
        if request.form['name'] and request.form['description']:
            updatedItem.name = request.form['name']
            updatedItem.description = request.form['description']
            session.add(updatedItem)
            session.commit()
            flash("category item updated!")
            return redirect(url_for('category_items', category_id=category_id))
        elif request.form['name'] and not request.form['description']:
            updatedItem.name = request.form['name']
            session.add(updatedItem)
            session.commit()
            flash("category item updated!")
            return redirect(url_for('category_items', category_id=category_id))
        elif request.form['description'] and not request.form['name']:
            updatedItem.description = request.form['description']
            session.add(updatedItem)
            session.commit()
            flash("category item updated!")
            return redirect(url_for('category_items', category_id=category_id))
    else:
        return render_template('editCategoryItem.html',
                               category_id=category_id, item_id=item_id,
                               item=updatedItem)


# Create route to delete a menu item:
# RESTRICT TO LOGGED IN USERS ONLY
@app.route('/<int:category_id>/<int:item_id>/delete/', methods=['GET', 'POST'])
def delete_category_item(category_id, item_id):
    deletedItem = session.query(CategoryItem).filter_by(id=item_id).one()
    if 'username' not in login_session:
        return redirect('login')
    if request.method == 'POST':
        session.delete(deletedItem)
        session.commit()
        flash("category item deleted!")
        return redirect(url_for('category_items', category_id=category_id))
    else:
        return render_template('deleteCategoryItem.html',
                               category_id=category_id, item_id=item_id,
                               item=deletedItem)


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
