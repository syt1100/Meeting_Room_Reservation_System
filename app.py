from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reservations.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        initialize_settings()

    @app.route('/')
    def index():
        today = datetime.today().strftime('%Y-%m-%d')
        reservations_today = Reservation.query.filter_by(date=today).all()
        return render_template('index.html', reservations=reservations_today)

    @app.route('/detail/<reservation_id>', methods=['GET'])
    def detail(reservation_id):
        reservation = Reservation.query.get(reservation_id)
        if reservation:
            return render_template('detail.html', reservation=reservation)
        else:
            return "Reservation not found", 404

    @app.route('/cancel/<reservation_id>', methods=['GET'])
    def cancel_reservation_view(reservation_id):
        if cancel_reservation(reservation_id):
            save_reservations()
            message = f"Reservation {reservation_id} cancelled successfully"
            return render_template('result.html', message=message)
        else:
            message = f"Reservation {reservation_id} not found"
            return render_template('result.html', message=message), 404

    @app.template_filter('endtime')
    def endtime(time_slot, format='%H:%M'):
        settings = Settings.query.first()
        time_delta = settings.time_delta  # Get the time_delta from the database
        end_time = (datetime.strptime(time_slot, '%H:%M') + timedelta(
            hours=time_delta)).time()  # Use the time_delta from the database
        return end_time.strftime(format)

    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%Y-%m-%d %H:%M'):
        #"""Format a date time object to a string."""
        return value.strftime(format)

    @app.route('/availability', methods=['GET'])
    def availability():
        date = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
        available_slots, booked_slots = get_slots_from_reservations(date)
        print(available_slots)  # Print the data to see its structure and types
        return render_template('availability.html', date=date, available_slots=available_slots,
                               booked_slots=booked_slots)

    @app.route('/reserve', methods=['GET', 'POST'])
    def reserve():
        if request.method == 'POST':
            date = request.form.get('date')
            room_number = request.form.get('room_number')
            time_slot = request.form.get('time_slot')
            name = request.form.get('name')
            reserve_agent = request.form.get('reserve_agent')
            special_request = request.form.get('special_request')

            reservation_id = f"{date.replace('-', '')}{room_number}{time_slot.replace(':', '')}"

            # Check if there is a conflicting reservation
            existing_reservation = Reservation.query.filter_by(id=reservation_id).first()
            if existing_reservation:
                settings = Settings.query.first()
                time_delta = settings.time_delta  # Get the time_delta from the database
                end_time = (datetime.strptime(time_slot, '%H:%M') + timedelta(
                    hours=time_delta)).time()  # Use the time_delta from the database
                message = f"Reservation failed: Room {room_number}, {time_slot} - {end_time.strftime('%H:%M')} is already reserved"
                return render_template('result.html', message=message, datetime=datetime)

            # Create the new Reservation object and add it to the session
            new_reservation = Reservation(id=reservation_id, room_number=room_number, time_slot=time_slot, name=name,
                                          date=date, reserve_agent=reserve_agent,
                                          special_request=special_request)  # 在创建新的预约时添加新的字段
            db.session.add(new_reservation)

            # Commit the reservation
            db.session.commit()
            settings = Settings.query.first()
            time_delta = settings.time_delta  # Get the time_delta from the database
            end_time = (datetime.strptime(time_slot, '%H:%M') + timedelta(
                hours=time_delta)).time()  # Use the time_delta from the database
            message = f"Reservation successful: Reservation ID {reservation_id}, Room {room_number}, {time_slot} - {end_time.strftime('%H:%M')} reserved by {name}"

            return render_template('result.html', message=message, datetime=datetime)
        else:
            date = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
            available_slots, booked_slots = get_slots_from_reservations(date)
            available_slots_js = json.dumps(available_slots)
            return render_template('reserve.html', slots=available_slots, date=date,
                                   available_slots_js=available_slots_js)

    @app.route('/search', methods=['GET'])
    def search_reservation():
        return render_template('search_reservation.html')

    @app.route('/search', methods=['POST'])
    def search_reservation_results():
        date = request.form.get('date')
        reservation_id = request.form.get('reservation_id')
        guest_name = request.form.get('guest_name')

        reservations = Reservation.query.filter(
            (Reservation.date == date) |
            (Reservation.id == reservation_id) |
            (Reservation.name.ilike(f'%{guest_name}%'))
        ).all()

        return render_template('search_results.html', reservations=reservations)

    @app.route('/cancel', methods=['GET', 'POST'])
    def cancel():
        if request.method == 'POST':
            reservation_id = request.form.get('reservation_id')
            if cancel_reservation(reservation_id):
                save_reservations()
                message = f"Reservation {reservation_id} cancelled successfully"
            else:
                message = f"Reservation {reservation_id} not found"
            return render_template('result.html', message=message)
        else:
            date = request.args.get('date')
            if date:
                # If date is given, get all reservations on this date
                settings = Settings.query.first()
                time_delta = settings.time_delta  # Get the time_delta from the database
                reservations = [
                    {
                        'reservation_id': r.id,
                        'room_name': rooms[r.room_number]['name'],
                        'start_time': datetime.strptime(f'{r.date} {r.time_slot}', '%Y-%m-%d %H:%M'),
                        'end_time': datetime.strptime(f'{r.date} {r.time_slot}', '%Y-%m-%d %H:%M') + timedelta(
                            hours=time_delta),
                        'name': r.name
                    }
                    for r in Reservation.query.filter_by(date=date)
                ]
            else:
                reservations = []
            return render_template('cancel.html', date=date, reservations=reservations)

    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        if request.method == 'POST':
            number_of_rooms = int(request.form.get('number_of_rooms'))
            time_slots = request.form.get('time_slots').split(',')
            time_delta = int(request.form.get('time_delta'))  # Get the time_delta from the form

            # Update the rooms and time slots
            update_rooms_and_time_slots(number_of_rooms, time_slots)

            # Save the settings to the database
            settings = Settings.query.first()
            settings.number_of_rooms = number_of_rooms
            settings.time_slots = ','.join(time_slots)
            settings.time_delta = time_delta  # Save the time_delta to the database
            db.session.commit()

            return redirect(url_for('index'))
        else:
            settings = Settings.query.first()
            number_of_rooms = len(rooms)
            time_slots = ','.join(rooms[next(iter(rooms))]['slots'].keys())
            time_delta = settings.time_delta  # Get the time_delta from the database

            return render_template('settings.html', number_of_rooms=number_of_rooms, time_slots=time_slots,
                                   time_delta=time_delta)

    @app.route('/stats', methods=['GET'])
    def stats():
        # Total number of reservations
        total_reservations = Reservation.query.count()

        # Reservations by room
        reservations_by_room = db.session.query(
            Reservation.room_number, db.func.count(Reservation.id)
        ).group_by(Reservation.room_number).all()

        # Reservations by time slot
        reservations_by_time_slot = db.session.query(
            Reservation.time_slot, db.func.count(Reservation.id)
        ).group_by(Reservation.time_slot).all()

        return render_template('stats.html', total_reservations=total_reservations,
                               reservations_by_room=reservations_by_room,
                               reservations_by_time_slot=reservations_by_time_slot)

    @app.route('/credit', methods=['GET'])
    def credit():
        version = 'Beta 0.01'  # Version Number
        updates = [
            {
                'date': '2023-05-11',
                'content': 'Fix some bugs '
            },
            {
                'date': '2023-05-10',
                'content': 'Release of Beta Version Beta 0.01 '
            },
            # Add new version info here
        ]
        return render_template('credit.html', version=version, updates=updates)

    return app

class Reservation(db.Model):
    id = db.Column(db.String, primary_key=True)
    room_number = db.Column(db.Integer, nullable=False)
    time_slot = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    date = db.Column(db.String, nullable=False)
    reserve_agent = db.Column(db.String, nullable=True)
    special_request = db.Column(db.String, nullable=True)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number_of_rooms = db.Column(db.Integer, nullable=False)
    time_slots = db.Column(db.String, nullable=False)
    time_delta = db.Column(db.Integer, default=2)  # Add time_delta in hours

# Load reservations from the database
def load_reservations():
    global reservations
    reservations = {r.id: r for r in Reservation.query.all()}

# Save reservations to the database
def save_reservations():
    db.session.commit()

# Define a function to reserve a slot
# Define a function to reserve a slot
def reserve_slot(room_number, time_slot, name, date):
    if rooms[room_number]['slots'][time_slot] is None and time_slot in rooms[room_number]['slots']:
        reservation_id = f"{date.replace('-', '')}{room_number:02d}{time_slot.replace(':', '')}"
        rooms[room_number]['slots'][time_slot] = name
        reservation = Reservation(id=reservation_id, room_number=room_number, time_slot=time_slot, name=name, date=date)
        db.session.add(reservation)
        db.session.commit()  # Commit the reservation to the database
        return reservation_id
    else:
        return None


# Renamed function from print_available_slots to get_slots
def get_slots_from_reservations(date):
    load_reservations()
    available_slots = {}
    booked_slots = []
    settings = Settings.query.first()
    time_delta = settings.time_delta  # Get the time_delta from the database

    for room_number in rooms:
        for time_slot in rooms[room_number]['slots']:
            start_time = datetime.strptime(f'{date} {time_slot}', '%Y-%m-%d %H:%M')
            end_time = start_time + timedelta(hours=time_delta)
            is_booked = False

            for reservation_id, reservation in reservations.items():
                if reservation.date == date and reservation.room_number == room_number and reservation.time_slot == time_slot:
                    is_booked = True
                    booked_slots.append({
                        'reservation_id': reservation_id,
                        'room_name': rooms[room_number]['name'],
                        'room_number': room_number,
                        'time_slot': time_slot,
                        'start_time': start_time,
                        'end_time': end_time,
                        'name': reservation.name
                    })
                    break

            if not is_booked:
                if room_number not in available_slots:
                    available_slots[room_number] = {
                        'name': rooms[room_number]['name'],
                        'slots': {}
                    }
                available_slots[room_number]['slots'][time_slot] = None

    return available_slots, booked_slots

# Cancel reservation
def cancel_reservation(reservation_id):
    reservation = Reservation.query.get(reservation_id)
    if reservation:
        room_number = reservation.room_number
        time_slot = reservation.time_slot
        rooms[room_number]['slots'][time_slot] = None
        db.session.delete(reservation)
        return True
    return False

#Define Room Settings
def update_rooms_and_time_slots(number_of_rooms, time_slots):
    global rooms
    new_rooms = {}

    for i in range(1, number_of_rooms + 1):
        new_rooms[i] = {
            'name': f'Room {i}',
            'slots': {slot.strip(): None for slot in time_slots}
        }

    rooms = new_rooms

def initialize_settings():
    global rooms
    settings = Settings.query.first()

    if settings:
        number_of_rooms = settings.number_of_rooms
        time_slots = settings.time_slots.split(',')
    else:
        # Default settings
        number_of_rooms = 4
        time_slots = ['18:00', '20:00']
        settings = Settings(number_of_rooms=number_of_rooms, time_slots=','.join(time_slots))
        db.session.add(settings)
        db.session.commit()

    update_rooms_and_time_slots(number_of_rooms, time_slots)

rooms = {}  # Initialize the rooms variable as an empty dictionary

if __name__ == '__main__':
    app = create_app()
    app.debug = False
    app.run()
