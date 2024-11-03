#!/usr/bin/python3
import cv2, math, os, json, traceback, io, time
print(cv2.__version__)

import numpy as np
import scipy.signal


#https://www.tensorflow.org/tutorials/keras/classification
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import datasets, layers, models
print(tf.__version__)

MODEL_FILE="/srv/boggle/new_model.h5"
IMG_DIM = 30
class_names = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
L = len(class_names)
model = tf.keras.models.load_model(MODEL_FILE)



RED = (0, 0, 255)
BLUE = (255, 0, 0)
GREEN = (0, 255, 0)
YELLOW = (0, 255, 255)
CONTOUR_THICKNESS = 2
MAX_DISP_DIM = 500

#a generic error
class BoggleError(Exception):
    def __init__(self, arg):
        self.strerror = arg
        self.args = {arg}

def four_point_transform(image, pts, size):
    w = size
    h = size
    ntl = [0, 0]
    ntr = [w, 0]
    nbr = [w, h]
    nbl = [0, h]
    location = np.float32(pts)
    x0 = pts[0][0]
    x2 = pts[2][0]
    #make sure the board ends up rotated the correct way
    if x0 < x2:
        newLocation = np.float32([ntl, nbl, nbr, ntr])
    else:
        newLocation = np.float32([ntr, ntl, nbl, nbr])
    M = cv2.getPerspectiveTransform(location, newLocation)
    warpedimage = cv2.warpPerspective(image, M, (w, h))
    return warpedimage

def resizeWithAspectRatio(image, maxDispDim, inter=cv2.INTER_AREA):
    w = image.shape[0] #TODO width and height are swapped here
    h = image.shape[1]

    ar = w / h
    #print(ar)
    if w > h:
        nw = maxDispDim
        nh = int(maxDispDim / ar)
    elif h > w:
        nh = maxDispDim
        nw = int(maxDispDim / ar)
    else:
        nh = maxDispDim
        nw = maxDispDim

    dim = None
    (h, w) = image.shape[:2]

    r = nw / float(w)
    dim = (nw, int(h * r))

    return cv2.resize(image, dim, interpolation=inter)

def imshow_fit(name, img, maxDispDim=MAX_DISP_DIM):
    if maxDispDim is not None:
        img = resizeWithAspectRatio(img, maxDispDim)
    cv2.imshow(name, img)

def findBestCtr(contours):
    bestArea = 0
    bestCtr = None
    for i, ctr in enumerate(contours):
        area = cv2.contourArea(ctr)
        # perimeter = cv2.arcLength(ctr, True)
        if area > bestArea:
            bestArea = area
            bestCtr = ctr
    return bestCtr


def angleEveryFew(ctr, step):
    angles = []
    # dists = []
    prev = ctr[-1]
    for i in range(0, len(ctr), step):
        curr = ctr[i]
        px, py = prev[0]
        cx, cy = curr[0]
        # angle = (px-cx)/(py-cy)
        angle = math.atan2(cy - py, cx - px)
        angles.append(angle)
        # dist = math.hypot(cx-px, cy-py)
        # dists.append(dist)
        prev = curr
    return angles


def angleAvg(angles):
    x = 0
    y = 0
    for angle in angles:
        x += math.cos(angle)
        y += math.sin(angle)
    return math.atan2(y, x)


def angleDiffAbs(angle1, angle2):
    return abs(((angle1 - angle2 + math.pi) % (2 * math.pi)) - math.pi)


def runningAvg(angles, history):
    result = []
    for i in range(len(angles)):
        # avg = 0
        vals2 = []
        for j in range(history):
            val = angles[int(i + j - history / 2) % len(angles)]
            vals2.append(val)
            # avg += val
        # avg /= history
        avg = angleAvg(vals2)
        result.append(avg)
    return result


def diffAbs(vals):
    diffs = []
    prev = vals[-1]
    for i in range(0, len(vals), 1):
        curr = vals[i]
        diff = angleDiffAbs(prev, curr) * 10
        diffs.append(diff)
        prev = curr
    return diffs


def debounce(bools, history):
    result = []
    for i in range(len(bools)):
        total = 0
        for j in range(history):
            val = bools[int(i + j - history / 2) % len(bools)]
            total += val
        result.append(int(total >= history / 2))
    return result


def findGaps(diffs):
    wasGap = True
    seamI = 0
    for i, diff in enumerate(diffs):
        isGap = diff
        if not isGap and not wasGap:
            seamI = i
            break
        wasGap = isGap

    xs = range(len(diffs))
    xs = [x for x in xs]
    xs_a = xs[seamI:]
    xs_a.extend(xs[:seamI])
    diffs_a = diffs[seamI:]
    diffs_a.extend(diffs[:seamI])

    xs2 = []
    diffs2 = []
    gapsStart = []
    gapsStartY = []
    gapsEnd = []
    gapsEndY = []
    wasGap = None
    gapwidth = 0
    for x, diff in zip(xs_a, diffs_a):
        isGap = diff
        if wasGap is None:
            wasGap = isGap
        if isGap:
            xs2.append(x)
            diffs2.append(diff)
            gapwidth += 1
        if isGap and not wasGap:
            gapsStart.append(x)
            gapsStartY.append(.5)
        if not isGap and wasGap:
            gapsEnd.append(x)
            gapsEndY.append(gapwidth)
            gapwidth = 0
        wasGap = isGap
    return gapsStart, gapsStartY, gapsEnd, gapsEndY, diffs2, xs2
    # gaps = [i for i in zip(gapsStart, gapsEnd, gapsEndY)]
    # return gaps, diffs, xs2


def top4gaps(gaps):
    def length_sort(gap):
        return -gap[2]

    gaps2 = sorted(gaps, key=length_sort)
    gaps2 = gaps2[:4]
    return [i for i in gaps if i in gaps2]


def invertGaps(gaps):
    segments = []
    prev = gaps[-1]
    for curr in gaps:
        segments.append((prev[1], curr[0]))
        prev = curr
    return segments


def findSidePoints(segments, ctr, step):
    sidePoints = []
    for seg in segments:
        if seg[1] > seg[0]:
            sidePoints.append(ctr[seg[0] * step:seg[1] * step])
        else:
            sidePoints.append(ctr[seg[0] * step:, :seg[1] * step])
    return sidePoints


def getEndVals(arr, fraction):
    if fraction >= 0.5: return arr
    l = len(arr)
    keep = int(fraction * l)
    keep = max(keep, 1)
    return np.concatenate((arr[:keep], arr[l - keep:]))


def fitSidePointsToLines(sidePoints):
    lines = []
    for sp in sidePoints:
        xs = np.zeros(len(sp), int)
        ys = np.zeros(len(sp), int)
        for i, pt in enumerate(sp):
            x, y = pt[0] #TODO if pt is empty
            xs[i] = x
            ys[i] = y
        lines.append(np.polyfit(xs, ys, 1))
    return lines


def findCorners(lines):
    points = []

    prev = lines[-1]
    for curr in lines:
        a1, b1 = prev
        a2, b2 = curr

        x = (b2 - b1) / (a1 - a2)
        y = np.polyval(curr, x)
        #if math.isnan(x): x = 0 #TODO
        #if math.isnan(y): y = 0
        points.append((int(x), int(y)))
        prev = curr
    return points


def drawLinesAndPoints(image, lines, points):
    width = image.shape[1]

    for l in lines:
        y1 = int(np.polyval(l, 0))
        y2 = int(np.polyval(l, width - 1))
        cv2.line(image, (0, y1), (width - 1, y2), RED, CONTOUR_THICKNESS)

    for point in points:
        cv2.circle(image, point, 4, BLUE, 3)

#https://scipy-cookbook.readthedocs.io/items/SignalSmooth.html
#window: np.ones (flat), np.hanning, np.hamming, np.bartlett, np.blackman
def smooth(x, window_len=11, window=np.hanning):
    if x.ndim != 1:
        raise ValueError("smooth only accepts 1 dimension arrays.")

    if x.size < window_len:
        raise ValueError("Input vector needs to be bigger than window size.")

    if window_len<3:
        return x

    s=np.r_[x[window_len-1:0:-1], x, x[-2:-window_len-1:-1]]
    w = window(window_len)
    y = np.convolve(w / w.sum(), s, mode='valid')
    return y


def findRowsOrCols(img, doCols, smoothFactor, ax):
    smoothFactor = int(smoothFactor * img.shape[0])
    #print("smoothFactor", smoothFactor)
    
    if doCols:
        title = "colSum"
        imgSum = cv2.reduce(img, 0, cv2.REDUCE_AVG, dtype=cv2.CV_32S)
        imgSum = imgSum[0]
    else:
        #row sum
        title = "rowSum"
        imgSum = cv2.reduce(img, 1, cv2.REDUCE_AVG, dtype=cv2.CV_32S)
        imgSum = imgSum.reshape(len(imgSum))
    
    imgSumSmooth = smooth(imgSum, smoothFactor*2)

    #https://qingkaikong.blogspot.com/2018/07/find-peaks-in-data.html
    #peaks_positive, _ = scipy.signal.find_peaks(imgSumSmooth, height=200, threshold = None, distance=60)
    dips, props = scipy.signal.find_peaks(-imgSumSmooth, height=(None,None), distance=30, prominence=(None,None))
    
    #threshold=(None,None), 
    #, plateau_size=(None,None)
    
    #print(props)

    prs = props["prominences"]
    if len(prs) < 6:
        top_6_dips = dips
        #print ("!!!! less than 6 dips")
        #raise BoggleError("less than 6 dips")
    else:
        prsIdx = sorted(range(len(prs)), key=lambda i: prs[i], reverse=True)
        #print(prsIdx)
        prsIdx = prsIdx[:6]
        #print(prsIdx)
        top_6_dips = [p for i,p in enumerate(dips) if i in prsIdx]

    #fig = plt.figure()
    #ax1 = fig.add_subplot(111)
    
    if ax is not None:
        q = [i for i in range(len(imgSumSmooth))]
        
        ax.plot(q, imgSumSmooth, 'b-', linewidth=2, label="smooth")
        ax.plot(np.linspace(smoothFactor,len(imgSumSmooth)-smoothFactor, len(imgSum)), imgSum, 'r-', linewidth=1, label=title)

        #ax.plot(
            #[q[p] for p in peaks_positive],
            #[imgSumSmooth[p] for p in peaks_positive],
            #'ro', label = 'positive peaks')
        
        ax.plot(
            [q[p] for p in dips],
            [imgSumSmooth[p] for p in dips],
            'go', label='dips')
        
        ax.plot(
            [q[p] for p in top_6_dips],
            [imgSumSmooth[p] for p in top_6_dips],
            'c.', label='top 6 dips')
        
        ax.legend(loc='best')
        
    #return top_6_dips
    #print("before clip", top_6_dips)
    top_6_dips_scaled = [np.clip(0, p-smoothFactor, len(imgSum)-1) for p in top_6_dips]
    return top_6_dips_scaled


def findBoggleBoard(image, normalPlots=True, harshErrors=False, generate=("debugimage", "debugmask", "contourPlotImg", "warpedimage", "imgSumPlotImg", "diceRaw", "dice")):
    resultImages = {}

    # maskThresholdMin = (108, 28, 12)
    # maskThresholdMax = (125, 255, 241)
    # maskThresholdMin = (108, 28, 6)
    # maskThresholdMax = (130, 255, 241)
    maskThresholdMin = (108, 28, 6)
    maskThresholdMax = (144, 255, 241)
    size = max(image.shape)
    #print("size", size)
    blurAmount = int(.02 * size)
    blurAmount = (blurAmount, blurAmount)
    # blurThreshold = 80
    blurThreshold = 40
    contourApprox = cv2.CHAIN_APPROX_NONE
    # contourApprox = cv2.CHAIN_APPROX_SIMPLE
    # contourApprox = cv2.CHAIN_APPROX_TC89_L1
    # contourApprox = cv2.CHAIN_APPROX_TC89_KCOS

    hsvimg = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsvimg, maskThresholdMin, maskThresholdMax)

    maskblur = cv2.blur(mask, blurAmount)
    # maskblur = cv2.threshold(maskblur, 80, 255, cv2.THRESH_BINARY_INV)
    maskblur = cv2.inRange(maskblur, (blurThreshold,), (255,))
    
    #API CHANGE: findContours no longer returns a modified image
    #contourimg, contours, hierarchy = cv2.findContours(maskblur, cv2.RETR_LIST, contourApprox)
    contours, hierarchy = cv2.findContours(maskblur, cv2.RETR_LIST, contourApprox)
    # print(hierarchy) #TODO
    
    bestCtr = findBestCtr(contours)
    # bestCtr = cv2.convexHull(bestCtr)

    #draw the contours for debugging
    if "debugimage" in generate:
        debugimage = image.copy()
        cv2.drawContours(debugimage, contours, -1, RED, CONTOUR_THICKNESS)
        cv2.drawContours(debugimage, [bestCtr], -1, BLUE, CONTOUR_THICKNESS)
    if "debugmask" in generate:
        debugmask = cv2.cvtColor(maskblur, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(debugmask, contours, -1, RED, CONTOUR_THICKNESS)
        cv2.drawContours(debugmask, [bestCtr], -1, BLUE, CONTOUR_THICKNESS)
    

    step = 10
    avgWindow = 0.1
    debounceFactor = .05
    
    angles = angleEveryFew(bestCtr, step)

    xs = range(len(angles))

    anglesAvg = runningAvg(angles, int(avgWindow * len(angles)))
    diffs = diffAbs(anglesAvg)
    
    avgDiff = np.mean(diffs)
    #print(avgDiff)
    
    binDiffs = [int(i > avgDiff) for i in diffs]
    binDiffs = debounce(binDiffs, int(len(binDiffs) * debounceFactor))
    gapsStart, gapsStartY, gapsEnd, gapsEndY, diffs2, xs2 = findGaps(binDiffs)
    gaps = [i for i in zip(gapsStart, gapsEnd, gapsEndY)]
    
    #scale for viewing on the plot
    gapsEndY2 = gapsEndY
    if len(gapsEndY) > 0:
        q = max(gapsEndY)
        if q > 6: gapsEndY2 = [i * 6 / q for i in gapsEndY]

    if "contourPlotImg" in generate:
        contourPlotImg = contourPlot(xs, xs2, angles, anglesAvg, diffs, diffs2, gapsStart, gapsStartY, gapsEnd, gapsEndY2, normalPlots)
        if contourPlotImg is not None:
            resultImages["contourPlotImg"] = contourPlotImg
    
    if len(gaps) < 4:
        print("!!!! less than 4 gaps")
        if harshErrors:
            raise BoggleError("less than 4 gaps")
        if "contourPlotImg" in generate:
            contourPlotImg = contourPlot(xs, xs2, angles, anglesAvg, diffs, diffs2, gapsStart, gapsStartY, gapsEnd, None, normalPlots)
            if contourPlotImg is not None:
                resultImages["contourPlotImg"] = contourPlotImg
        
        if "debugmask" in generate:
            resultImages["debugmask"] = debugmask
        if "debugimage" in generate:
            resultImages["debugimage"] = debugimage
        return resultImages, None
    
    endFraction = 0.01
    
    gaps = top4gaps(gaps)
    segments = invertGaps(gaps)
    sidePoints = findSidePoints(segments, bestCtr, step)
    sidePoints = [getEndVals(sp, endFraction) for sp in sidePoints]
    #print("sidepoints len", len(sidePoints[0]))
    
    
    lines = fitSidePointsToLines(sidePoints)
    points = findCorners(lines)
    if "debugimage" in generate:
        cv2.drawContours(debugimage, sidePoints, -1, YELLOW, CONTOUR_THICKNESS)
        drawLinesAndPoints(debugimage, lines, points)
        resultImages["debugimage"] = debugimage
    if "debugmask" in generate:
        cv2.drawContours(debugmask, sidePoints, -1, YELLOW, CONTOUR_THICKNESS)
        drawLinesAndPoints(debugmask, lines, points)
        resultImages["debugmask"] = debugmask

    npPoints = np.array(points)
    size = 300
    warpedimage = four_point_transform(image, npPoints, size)
    warpgray = cv2.cvtColor(warpedimage, cv2.COLOR_BGR2GRAY)
    
    if "warpedimage" in generate:
        resultImages["warpedimage"] = warpedimage
    
    if "warpgray" in generate:
        resultImages["warpgray"] = warpgray
    
    smoothFactor = .05
    
    if "imgSumPlotImg" in generate:
        fig, (ax0, ax1) = plt.subplots(2, figsize=(8,10))
    else:
        ax0 = ax1 = None
    
    rowSumLines = findRowsOrCols(warpgray, False, smoothFactor, ax0)
    #print("rows", rowSumLines)
    colSumLines = findRowsOrCols(warpgray, True, smoothFactor, ax1)
    #print("cols", colSumLines)
    
    
    if "imgSumPlotImg" in generate:
        if normalPlots:
            plt.show(block=False)
        else:
            resultImages["imgSumPlotImg"] = plotToImg()


    if len(rowSumLines) < 6 or len(colSumLines) < 6:
        print("!!!! not enough grid lines")
        if harshErrors:
            raise BoggleError("not enough gridlines")
        return resultImages, None
    
    #fix the outermost lines of the board
    h1 = rowSumLines[2] - rowSumLines[1]
    h2 = rowSumLines[3] - rowSumLines[2]
    h3 = rowSumLines[4] - rowSumLines[3]
    h = max(h1, h2, h3)
    
    newCSL0 = colSumLines[1] - h
    if newCSL0 > colSumLines[0]:
        colSumLines[0] = newCSL0
    newCSL5 = colSumLines[4] + h
    if newCSL5 < colSumLines[5]:
        colSumLines[5] = newCSL5
    
    w1 = colSumLines[2] - colSumLines[1]
    w2 = colSumLines[3] - colSumLines[2]
    w3 = colSumLines[4] - colSumLines[3]
    w = max(w1, w2, w3)
    
    newRSL0 = rowSumLines[1] - w
    if newRSL0 > rowSumLines[0]:
        rowSumLines[0] = newRSL0
    newRSL5 = rowSumLines[4] + w
    if newRSL5 < rowSumLines[5]:
        rowSumLines[5] = newRSL5

    #print("rows2", rowSumLines)
    #print("cols2", colSumLines)

    #just display
    if "diceRaw" in generate:
        plt.figure(figsize=(10,10))
        i = 1
        for y in range(5):
            for x in range(5):
                plt.subplot(5,5,i)
                i += 1
                plt.xticks([])
                plt.yticks([])
                plt.grid(False)
                minX = colSumLines[x]
                maxX = colSumLines[x+1]
                minY = rowSumLines[y]
                maxY = rowSumLines[y+1]
                crop_img = warpgray[minY:maxY, minX:maxX]
                plt.imshow(crop_img, cmap=plt.cm.gray)
        if normalPlots:
            plt.show(block=False)
        else:
            resultImages["diceRaw"] = plotToImg()

    
    if "dice" in generate:
        plt.figure(figsize=(10,10))
        i = 1

    letterResize = 30
    #make square, resize, display, and save to an array
    letterImgs = []
    for y in range(5):
        letterImgRow = []
        for x in range(5):
            minX = colSumLines[x]
            maxX = colSumLines[x+1]
            minY = rowSumLines[y]
            maxY = rowSumLines[y+1]
            w = maxX - minX
            h = maxY - minY
            #print("w,h 1:", w, h)
            d = abs(w - h)
            if d > 0:
                if int(d/2) == d/2:
                    #even difference
                    d1 = d2 = int(d/2)
                else:
                    #odd difference
                    d1 = int((d-1)/2)
                    d2 = int((d+1)/2)
                if w > h:
                    #wider than it is tall
                    minX += d1
                    maxX -= d2
                else:
                    #taller than it is wide
                    minY += d1
                    maxY -= d2
            #print("w,h 2:", maxX-minX, maxY-minY)
            crop_img = warpgray[minY:maxY, minX:maxX]
            letterImg = cv2.resize(crop_img, (letterResize,letterResize), interpolation=cv2.INTER_AREA)
            if "dice" in generate:
                plt.subplot(5,5,i)
                i += 1
                plt.xticks([])
                plt.yticks([])
                plt.grid(False)
                plt.imshow(letterImg, cmap=plt.cm.gray)
            letterImgRow.append(letterImg)
        letterImgs.append(letterImgRow)

    if "dice" in generate:
        if normalPlots:
            plt.show(block=False)
        else:
            resultImages["dice"] = plotToImg()
    
    return resultImages, letterImgs


def processImage(filepath):
    image = cv2.imread(filepath)
    resultImages, letters5x5grid = findBoggleBoard(image, normalPlots=False, harshErrors=True, generate=("warpedimage"))
    cv2.imwrite(filepath+"_warpedimage.png", resultImages["warpedimage"])
    
    lettersGuessed = ""
    confidence = []
    num_rows = 5
    num_cols = 5
    num_images = num_rows*num_cols
    for row in range(num_rows):
        for col in range(num_cols):
            letterImg = letters5x5grid[row][col]
            letterImg = letterImg / 255
#             print(letterImg.shape)
            letterImg = (np.expand_dims(letterImg,0))
            letterImg = (np.expand_dims(letterImg,axis=3))
#             print(letterImg.shape)
            pred = model.predict(letterImg)[0]
            letter = class_names[np.argmax(pred)]
            lettersGuessed += letter
            confidence.append(np.max(pred))
    return lettersGuessed, confidence

"""
# letters5x5gridLabelsStr = "IZEIMFLTYTOSEINHETNORRISU" #00162
# letters5x5gridLabelsStr = "DONLIEEIIESAPYWTAAKLTINRE" #00164
# letters5x5gridLabelsStr = "RAOCODSEERGAPEWORXRHELWNT" #00165
# letters5x5gridLabelsStr = "RONLICTSSDNMPPNUAEQIHINRM" #00170
letters5x5gridLabelsStr = "VANUIRAUHESKEITTDPRCGOUCA" #00171, 00160
# letters5x5gridLabelsStr = "IXESMFLEYTOSEENOETNRRRIWM" #00172, 00161

#process 1 image
IMAGE_FILE = '/home/johanv/nextcloud/projects/boggle2.0/cascademan/categories/5x5/images/00160.jpg'
lettersGuessed, confidence = processImage(IMAGE_FILE)

right = "".join([str(int(a == b)) for a,b in zip(lettersGuessed, letters5x5gridLabelsStr)])

confidence_right = []
confidence_wrong = []

for i, c in enumerate(confidence):
    if right[i] == "1":
        confidence_right.append(c)
    else:
        confidence_wrong.append(c)

print("guess: " + lettersGuessed)
print("real:  " + letters5x5gridLabelsStr)
print("right: " + right)
# print("confidence:", confidence)
# print("confidence_right:", confidence_right)
# print("confidence_wrong:", confidence_wrong)
"""
