import cv2
import numpy as np
from midiutil import MIDIFile
from matplotlib import pyplot as plt
from keras.preprocessing.image import img_to_array
from keras.models import load_model
import pickle
from bound import BoundingBox
from note import Note

import warnings
warnings.filterwarnings("ignore")

MODEL_NAME = "model/smallvgg.model"
LABELBIN_NAME = "model/lb.pickle"
DURATION = {
    "Quarter-Note": 1,
    "Eighth-Note": 0.5,
    "Sixteenth-Note": 0.25
}

def get_staffs(img, verbose=False):
    """
	It takes image as input and find staffs
	:param img: original image
	:param verbose: enable verbose output
	:return: list of bounding boxes for staffs
	"""

    img_copy = np.copy(img)
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bw = cv2.bitwise_not(img_gray)
    thresh = cv2.adaptiveThreshold(bw, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)

    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 2))
    dilation = cv2.dilate(thresh, kernel, iterations=10)
    # get contours
    _, contours, hierarchy = cv2.findContours(dilation, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # for each contour create bounding rectangle
    bounding_boxes = []
    for contour in contours:
        (x, y, w, h) = cv2.boundingRect(contour)
        box = BoundingBox(x, y, w, h)
        bounding_boxes.append(box)

    boxes_sorted = sorted(bounding_boxes, key=lambda x: x.w, reverse=True)
    # threshold width
    tw = boxes_sorted[0].w - 100
    # threshold height
    th = boxes_sorted[0].h - 10

    staffs = []
    for box in bounding_boxes:
        # discard rectangles that are smaller than threshold
        if box.w < tw or box.h < th:
            continue

        staffs.append(box)
        cv2.rectangle(img_copy, box.pt1, box.pt2, (255, 0, 0), 1)

    if verbose:
        # display image with contours
        cv2.imshow('Staffs detection', img_copy)
        cv2.waitKey(0)

    return list(reversed(staffs))


def get_staves(img, staffs, verbose=False):
    """
	Return list of staves images.
	:param img: original image.
	:param staffs: list of bounding boxes for staffs
	:param verbose: enable verbose output
	:return: list of staves images
	"""

    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Apply adaptiveThreshold at the bitwise_not of gray
    img_gray = cv2.bitwise_not(img_gray)
    _, bw = cv2.threshold(img_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    staves = []
    i = 1
    for staff in staffs:
        # Get cropped image
        crop_img = bw[staff.pt1[1]:staff.pt2[1], staff.pt1[0]:staff.pt2[0]]

        # Create the image that will use to extract the horizontal lines
        horizontal = np.copy(crop_img)

        # Specify size on horizontal axis
        cols = horizontal.shape[1]
        horizontal_size = cols // 30

        # Create structure element for extracting horizontal lines through morphology operations
        horizontal_structure = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_size, 1))
        horizontal = cv2.erode(horizontal, horizontal_structure)
        horizontal = cv2.dilate(horizontal, horizontal_structure)
        staves.append(horizontal)

        # if verbose:
        #     i += 1
        #     cv2.imshow('Stave' + str(i), horizontal)
        #     cv2.waitKey(0)

    return staves


def detect_lines(img, staves, staffs, verbose=False):
    """
	Return list of lines positions by staffs.
	:param img: original image
	:param staves: list of staves images
	:param staffs: list of bounding boxes for staffs
	:param verbose: enable verbose output
	:return:
	"""

    img_copy = np.copy(img)
    lines_pos = []
    for stave, staff in zip(staves, staffs):
        lines = list((ind + staff.y, val) for ind, val in enumerate(stave.sum(axis=1)))
        lines = sorted(lines, key=lambda x: x[1], reverse=True)[:5]
        lines_pos.append([l[0] for l in lines])

    if (verbose):
        points = []
        for lines in lines_pos:
            for line in lines:
                points.append([0, line])
                points.append([img_copy.shape[1], line])
        points = np.array(points).reshape((-1, 2, 2))
        cv2.polylines(img_copy, points, False, (0, 0, 255), 1)
        cv2.imshow('Detected lines', img_copy)
        cv2.waitKey(0)

    return lines_pos


def fit_matching(img, templates, threshold, verbose=False):
    """
    Return best scale and positions.
	:param img: original image
	:param templates: list of templates
	:param threshold:
	:return: best scale, best positions
	"""

    best_positions_count = -1
    best_positions = []
    best_scale = 1
    w = h = 0
    for scale in [i / 100.0 for i in range(30, 100, 3)]:
        positions_count = 0
        positions = []
        for template in templates:
            template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            matching = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
            matching = np.where(matching >= threshold)
            positions_count += len(matching[0])
            positions += map(list, zip(*matching[::-1]))

            if verbose:
                print("Scale: {}, detected objects: {}".format(scale, positions_count))

            if positions_count > best_positions_count:
                best_positions_count = positions_count
                best_positions = positions
                best_scale = scale
                w, h = template.shape[::-1]
            elif positions_count < best_positions_count:
                pass
    if verbose:
        for pt in best_positions:
            cv2.rectangle(img, pt, (pt[0] + w, pt[1] + h), (0, 0, 255), 1)
        cv2.imshow('Matching', img)
        cv2.waitKey(0)

    return best_positions, best_scale


def detect(img, staffs, templates, threshold, verbose=False, color=(0, 255, 0)):
    """
	Detect objects using templates and return objects positions.
	:param img: original image
	:param staffs: list of bounding boxes for staffs
	:param templates: list of templates
	:param threshold: threshold
	:param verbose: enable verbose output
	:return: multidimensional list of bounding boxes by staffs
	"""

    img_copy = np.copy(img)
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    matching_results = []
    for staff in staffs:
        crop_img = img_gray[staff.pt1[1]:staff.pt2[1], staff.pt1[0]:staff.pt2[0]]
        positions, scale = fit_matching(crop_img, templates, threshold)

        tw, th = templates[0].shape[::-1]
        tw *= scale
        th *= scale

        bounding_boxes = []
        for i in range(0, len(positions)):
            x = positions[i][0] + staff.x
            y = positions[i][1] + staff.y
            box = BoundingBox(x, y, tw, th)
            bounding_boxes.append(box)

        matching_results.append(np.copy(bounding_boxes))

    if verbose:
        for boxes in matching_results:
            for box in boxes:
                box.draw(img_copy, color, 1)
        cv2.imshow("Detection", img_copy)
        cv2.waitKey(0)

    return matching_results


def merge_boxes(bounding_boxes, threshold):
    """
	Merge bounding boxes that overlap each over and return list of merged bounding boxes.
	:param bounding_boxes: list of bounding boxes
	:param threshold: threshold that defines merging
    :return: list of merged bounding boxes
	"""

    filtered_boxes = []
    bounding_boxes = bounding_boxes.tolist()
    while len(bounding_boxes) > 0:
        box = bounding_boxes.pop(0)
        bounding_boxes.sort(key=lambda b: b.get_distance(box))
        is_merging = True
        while is_merging:
            is_merging = False
            i = 0
            for _ in range(len(bounding_boxes)):
                if box.get_overlap_ratio(bounding_boxes[i]) > threshold or bounding_boxes[i].get_overlap_ratio(box):
                    box = box.merge(bounding_boxes.pop(i))
                    is_merging = True
                elif bounding_boxes[i].get_distance(box) > box.w / 2 + bounding_boxes[i].w / 2:
                    break
                else:
                    i += 1
        filtered_boxes.append(box)

    return filtered_boxes


def preprocess_image(img):
    img = cv2.resize(img, (96, 96))
    img = img.astype("float") / 255.0
    img = img_to_array(img)
    img = np.expand_dims(img, axis=0)

    return img


def define_durations(img, staffs, notes_boxes, verbose=False):
    img_copy = np.copy(img)
    notes_boxes_copy = np.copy(notes_boxes)

    model = load_model(MODEL_NAME)
    lb = pickle.loads(open(LABELBIN_NAME, "rb").read())

    all_durations = []
    for i, boxes in enumerate(notes_boxes_copy):
        y_staff = staffs[i].y
        height = staffs[i].h
        durations = []
        for box in boxes:
            box.x -= int(box.w)
            box.w += 2 * box.w
            box.y = y_staff
            box.h = height

            if verbose:
                box.draw(img_copy, (200, 200, 50), 1)

            note_img = img_copy[box.y:int(box.y + box.h), box.x:int(box.x + box.w)]
            note_img = preprocess_image(note_img)
            proba = model.predict(note_img)[0]
            idx = np.argmax(proba)
            label = lb.classes_[idx]
            durations.append(DURATION[label])
        all_durations.append(durations)

    if verbose:
        cv2.imshow("Boxes", img_copy)
        cv2.waitKey(0)

    return all_durations


def get_pitches(staff, lines_pos, notes_boxes, sharp_notes=None, flat_notes=None, duration=None):
    """
	Return list of Note objects.
	:param lines_pos: y-coordinate of the lines
	:param notes_boxes: list of notes bounding boxes
	:param sharp_notes: list of sharps
	:param flat_notes: list of flats
	:param duration: duration of notes
	:return: list of Note objects
	"""

    if type(duration) is int or duration is None:
        duration = [duration] * len(notes_boxes)

    notes = []
    gap_height = (lines_pos[1] - lines_pos[0]) / 2
    middle = lines_pos[1] + gap_height

    for i, note_box in enumerate(notes_boxes):
        v = (note_box.middle[1] - middle) / gap_height
        note_ind = int((note_box.middle[1] - middle) / gap_height)
        if note_ind in Note.NOTES.keys():
            label = Note.NOTES[note_ind][0]
            pitch = Note.NOTES[note_ind][1]
            if sharp_notes:
                if any(sharp.label[0] == label[0] for sharp in sharp_notes):
                    label += '#'
                    pitch += 1
            if flat_notes:
                if any(flat.label[0] == label[0] for flat in flat_notes):
                    label += 'b'
                    pitch -= 1
            notes.append(Note(label, pitch, duration[i], note_box))

    return notes


def convert_to_midi(notes, name):
    """
    Convert notes into MIDI file.
	:param notes: list of notes
	:return: MIDI file
	"""

    track = 0
    channel = 0
    time = 0
    tempo = 100
    volume = 100

    midi_file = MIDIFile(1)
    midi_file.addTempo(track, time, tempo)

    for note in notes:
        midi_file.addNote(track, channel, note.pitch, time, note.duration, volume)
        time += note.duration

    with open("results/{}.mid".format(name), "wb") as output_file:
        midi_file.writeFile(output_file)


def search_staffs(img, staffs, verbose=True):

    img_copy = img
    cv2.imwrite("staff.png", img_copy)
    img_gray = cv2.cvtColor(img_copy, cv2.COLOR_BGR2GRAY)
    bw = cv2.bitwise_not(img_gray)
    thresh = cv2.adaptiveThreshold(bw, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, -2)
    # cv2.imshow("Thresh", thresh)
    # cv2.imshow("BW", bw)
    # cv2.waitKey(0)

    horizontal_sum = np.sum(thresh, axis=1)
    # print(horizontal_sum)
    y = np.arange(0, len(horizontal_sum), 1)
    # plt.plot(horizontal_sum, y, c='g')
    # plt.xlabel("X")
    # plt.ylabel("Y")
    # plt.savefig("hproj.png")

    peaks = [(pos, val) for pos, val in zip(y, horizontal_sum)]
    peaks.sort(key=lambda x: x[1], reverse=True)
    # print(peaks)

    thresh = cv2.bitwise_not(thresh)


    # print(thresh)
    for i in range(1, thresh.shape[0] - 1):
        for j in range(thresh.shape[1]):
            if thresh[i][j] == 0 and thresh[i - 1][j] == 255 and thresh[i + 1][j]:
                thresh[i][j] = 255

    cv2.imwrite("removal_lines.png", thresh)

    return thresh
